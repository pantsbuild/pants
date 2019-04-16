# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil
from abc import abstractmethod

from pants.backend.native.config.environment import Linker, Platform
from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.native.tasks.native_compile import ObjectFiles
from pants.backend.native.tasks.native_task import NativeTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.util.dirutil import safe_mkdir_for
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass, classproperty
from pants.util.objects import datatype
from pants.util.process_handler import subprocess


class SharedLibrary(datatype(['name', 'path'])): pass


class NativeBinary(datatype(['binary_output_file'])): pass


class LinkSharedLibraryRequest(datatype([
    ('linker', Linker),
    ('object_files', tuple),
    ('native_artifact', NativeArtifact),
    'output_dir',
    ('external_lib_dirs', tuple),
    ('external_lib_names', tuple),
])):
  pass


class LinkObjectFiles(NativeTask, AbstractClass):

  options_scope = 'link-shared-libraries'

  @classmethod
  def prepare(cls, options, round_manager):
    super(LinkObjectFiles, cls).prepare(options, round_manager)
    round_manager.require(ObjectFiles)

  @property
  def cache_target_dirs(self):
    return True

  @classmethod
  def implementation_version(cls):
    return super(LinkObjectFiles, cls).implementation_version() + [('LinkObjectFiles', 1)]

  class LinkObjectFilesError(TaskError): pass

  @abstractmethod
  @classproperty
  def linker_args(cls):
    """Arguments for the linker command line to generate e.g. shared libraries vs binaries.

    :returns: a dict mapping (normalized os name) -> (list of string arguments).
    :rtype: dict
    """

  def linker(self, native_library_target):
    # NB: we are using the C++ toolchain here for linking every type of input, including compiled C
    # source files.
    return self.get_cpp_toolchain_variant(native_library_target).cpp_linker

  @memoized_property
  def platform(self):
    # TODO: convert this to a v2 engine dependency injection.
    return Platform.current

  def native_artifact_targets(self):
    return self.get_targets(NativeLibrary.produces_ctypes_native_library)

  @abstractmethod
  def process_result(self, vt, result):
    """Do something with the result of linking, typically adding it to a v1 product.

    The `result` argument here is produced by either `.collect_output()` (if the target wasn't
    cached) or `.retrieve_output_from_cache()` (if it was cached)."""

  def execute(self):
    targets_providing_artifacts = self.native_artifact_targets()
    compiled_objects_product = self.context.products.get(ObjectFiles)

    with self.invalidated(targets_providing_artifacts,
                          invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.all_vts:
        if vt.valid:
          linked_output = self.retrieve_output_from_cache(vt)
        else:
          # TODO: We need to partition links based on proper dependency edges and not
          # perform a link to every packaged_native_library() for all targets in the closure.
          # https://github.com/pantsbuild/pants/issues/6178
          link_request = self._make_link_request(vt, compiled_objects_product)
          self.context.log.debug("link_request: {}".format(link_request))
          linked_output = self._execute_link_request(link_request)

        self.process_result(vt, linked_output)

  @abstractmethod
  def retrieve_output_from_cache(self, vt):
    """Given a versioned target, retrieve the linked output from its cache directory.

    The return type of this method is task-specific, and this is consumed in `.process_result()`.
    """

  @abstractmethod
  def collect_output(self, native_artifact, output_file):
    """Given a declaration for a native_artifact() and an output file, generate a result.

    The return type of this method is task-specific, and this is consumed in `.process_result()`.
    """

  @abstractmethod
  def get_output_filename(self, native_artifact):
    """Given a declaration for a native_artifact(), return the correct output filename.

    E.g. for shared libraries, this would be a filename ending in .dylib or .so.
    :rtype: string
    """

  def _make_link_request(self, vt, compiled_objects_product):
    self.context.log.debug("link target: {}".format(vt.target))

    deps = self.native_deps(vt.target)

    all_compiled_object_files = []
    for dep_tgt in deps:
      if compiled_objects_product.get(dep_tgt):
        self.context.log.debug("dep_tgt: {}".format(dep_tgt))
        object_files = self._retrieve_single_product_at_target_base(
          compiled_objects_product, dep_tgt)
        self.context.log.debug("object_files: {}".format(object_files))
        object_file_paths = object_files.file_paths()
        self.context.log.debug("object_file_paths: {}".format(object_file_paths))
        all_compiled_object_files.extend(object_file_paths)

    external_lib_dirs = []
    external_lib_names = []
    for ext_dep in self.packaged_native_deps(vt.target):
      external_lib_dirs.append(
        os.path.join(get_buildroot(), ext_dep._sources_field.rel_path, ext_dep.lib_relpath))
      external_lib_names.extend(ext_dep.native_lib_names)

    link_request = LinkSharedLibraryRequest(
      linker=self.linker(vt.target),
      object_files=tuple(all_compiled_object_files),
      native_artifact=vt.target.ctypes_native_library,
      output_dir=vt.results_dir,
      external_lib_dirs=tuple(external_lib_dirs),
      external_lib_names=tuple(external_lib_names))

    self.context.log.debug(repr(link_request))

    return link_request

  def _execute_link_request(self, link_request):
    object_files = link_request.object_files

    if len(object_files) == 0:
      raise self.LinkObjectFilesError("No object files were provided in request {}!"
                                          .format(link_request))

    linker = link_request.linker
    native_artifact = link_request.native_artifact
    output_dir = link_request.output_dir
    output_file_path = os.path.join(output_dir, self.get_output_filename(native_artifact))

    self.context.log.debug("output_file_path: {}".format(output_file_path))
    # We are executing in the results_dir, so get absolute paths for everything.
    cmd = ([linker.exe_filename] +
           self.platform.resolve_for_enum_variant(self.linker_args) +
           linker.extra_args +
           ['-o', os.path.abspath(output_file_path)] +
           ['-L{}'.format(lib_dir) for lib_dir in link_request.external_lib_dirs] +
           ['-l{}'.format(lib_name) for lib_name in link_request.external_lib_names] +
           [os.path.abspath(obj) for obj in object_files])

    self.context.log.info("selected linker exe name: '{}'".format(linker.exe_filename))
    self.context.log.debug("linker argv: {}".format(cmd))

    env = linker.invocation_environment_dict
    self.context.log.debug("linker invocation environment: {}".format(env))

    with self.context.new_workunit(name='link-shared-libraries',
                                   labels=[WorkUnitLabel.LINKER]) as workunit:
      try:
        process = subprocess.Popen(
          cmd,
          cwd=output_dir,
          stdout=workunit.output('stdout'),
          stderr=workunit.output('stderr'),
          env=env)
      except OSError as e:
        workunit.set_outcome(WorkUnit.FAILURE)
        raise self.LinkObjectFilesError(
          "Error invoking the native linker with command {cmd} and environment {env} "
          "for request {req}: {err}."
          .format(cmd=cmd, env=env, req=link_request, err=e),
          e)

      rc = process.wait()
      if rc != 0:
        workunit.set_outcome(WorkUnit.FAILURE)
        raise self.LinkObjectFilesError(
          "Error linking native objects with command {cmd} and environment {env} "
          "for request {req}. Exit code was: {rc}."
          .format(cmd=cmd, env=env, req=link_request, rc=rc))

    return self.collect_output(native_artifact, output_file_path)


class LinkSharedLibraries(LinkObjectFiles):
  # TODO: validate that all shared libraries that a target depends on have a unique name! Otherwise
  # we can't link them with `-l` in the same command line!

  @classmethod
  def product_types(cls):
    return [SharedLibrary]

  @classproperty
  def linker_args(cls):
    return {
      'darwin': ['-Wl,-dylib'],
      'linux': ['-shared'],
    }

  def get_output_filename(self, native_artifact):
    return native_artifact.as_shared_lib(self.platform)

  def retrieve_output_from_cache(self, vt):
    native_artifact = vt.target.ctypes_native_library
    path_to_cached_lib = os.path.join(
      vt.results_dir, native_artifact.as_shared_lib(self.platform))
    if not os.path.isfile(path_to_cached_lib):
      raise self.LinkObjectFilesError("The shared library at {} does not exist!"
                                          .format(path_to_cached_lib))
    return SharedLibrary(name=native_artifact.lib_name, path=path_to_cached_lib)

  def collect_output(self, native_artifact, output_file):
    return SharedLibrary(name=native_artifact.lib_name, path=output_file)

  def process_result(self, vt, result):
    shared_libs_product = self.context.products.get(SharedLibrary)
    self._add_product_at_target_base(shared_libs_product, vt.target, result)


class LinkBinaries(LinkObjectFiles):

  @classproperty
  def linker_args(cls):
    return {
      'darwin': ['-Wl,-execute'],
      'linux': [],
    }

  def get_output_filename(self, native_artifact):
    return native_artifact.lib_name

  def native_artifact_targets(self):
    return set(super(LinkBinaries, self).native_artifact_targets()) & set(self.context.target_roots)

  def retrieve_output_from_cache(self, vt):
    native_artifact = vt.target.ctypes_native_library
    bin_path = os.path.join(vt.results_dir, native_artifact.lib_name)
    if not os.path.isfile(bin_path):
      raise self.LinkObjectFilesError('binary at {} does not exist!'.format(bin_path))
    return NativeBinary(binary_output_file=bin_path)

  def collect_output(self, native_artifact, output_file):
    return NativeBinary(binary_output_file=output_file)

  def process_result(self, vt, result):
    binary_output_path = result.binary_output_file
    native_artifact = vt.target.ctypes_native_library
    distdir = self.get_options().pants_distdir
    dist_output_bin = os.path.join(distdir, self.get_output_filename(native_artifact))
    safe_mkdir_for(dist_output_bin)
    shutil.copy(binary_output_path, dist_output_bin)
