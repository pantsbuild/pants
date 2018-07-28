# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.native.config.environment import Linker, LLVMCppToolchain, Platform
from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.native.tasks.native_compile import NativeTargetDependencies, ObjectFiles
from pants.backend.native.tasks.native_external_library_fetch import NativeExternalLibraryFiles
from pants.backend.native.tasks.native_task import NativeTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.util.collections import assert_single_element
from pants.util.memo import memoized_property
from pants.util.objects import datatype
from pants.util.process_handler import subprocess


class SharedLibrary(datatype(['name', 'path'])): pass


class LinkSharedLibraryRequest(datatype([
    ('linker', Linker),
    ('object_files', tuple),
    ('native_artifact', NativeArtifact),
    'output_dir',
    ('external_lib_dirs', tuple),
    ('external_lib_names', tuple),
])):

  @classmethod
  def with_external_libs_product(cls, external_libs_product=None, *args, **kwargs):
    if external_libs_product is None:
      lib_dirs = ()
      lib_names = ()
    else:
      lib_dirs = (external_libs_product.lib_dir,)
      lib_names = external_libs_product.lib_names

    return cls(*args, external_lib_dirs=lib_dirs, external_lib_names=lib_names, **kwargs)


class LinkSharedLibraries(NativeTask):

  options_scope = 'link-shared-libraries'

  @classmethod
  def product_types(cls):
    return [SharedLibrary]

  @classmethod
  def prepare(cls, options, round_manager):
    super(LinkSharedLibraries, cls).prepare(options, round_manager)
    round_manager.require(NativeTargetDependencies)
    round_manager.require(ObjectFiles)
    round_manager.optional_product(NativeExternalLibraryFiles)

  @property
  def cache_target_dirs(self):
    return True

  @classmethod
  def implementation_version(cls):
    return super(LinkSharedLibraries, cls).implementation_version() + [('LinkSharedLibraries', 0)]

  class LinkSharedLibrariesError(TaskError): pass

  @classmethod
  def subsystem_dependencies(cls):
    return super(LinkSharedLibraries, cls).subsystem_dependencies() + (NativeToolchain.scoped(cls),)

  @memoized_property
  def _native_toolchain(self):
    return NativeToolchain.scoped_instance(self)

  @memoized_property
  def _cpp_toolchain(self):
    return self._request_single(LLVMCppToolchain, self._native_toolchain).cpp_toolchain

  @memoized_property
  def linker(self):
    return self._cpp_toolchain.cpp_linker

  @memoized_property
  def platform(self):
    # FIXME: convert this to a v2 engine dependency injection.
    return Platform.create()

  def _retrieve_single_product_at_target_base(self, product_mapping, target):
    self.context.log.debug("product_mapping: {}".format(product_mapping))
    self.context.log.debug("target: {}".format(target))
    product = product_mapping.get(target)
    single_base_dir = assert_single_element(product.keys())
    single_product = assert_single_element(product[single_base_dir])
    return single_product

  def execute(self):
    targets_providing_artifacts = self.context.targets(NativeLibrary.produces_ctypes_native_library)
    native_target_deps_product = self.context.products.get(NativeTargetDependencies)
    compiled_objects_product = self.context.products.get(ObjectFiles)
    shared_libs_product = self.context.products.get(SharedLibrary)
    external_libs_product = self.context.products.get_data(NativeExternalLibraryFiles)

    all_shared_libs_by_name = {}

    with self.invalidated(targets_providing_artifacts,
                          invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.all_vts:
        if vt.valid:
          shared_library = self._retrieve_shared_lib_from_cache(vt)
        else:
          # FIXME: We need to partition links based on proper dependency edges and not
          # perform a link to every native_external_library for all targets in the closure.
          # https://github.com/pantsbuild/pants/issues/6178
          link_request = self._make_link_request(
            vt, compiled_objects_product, native_target_deps_product, external_libs_product)
          self.context.log.debug("link_request: {}".format(link_request))
          shared_library = self._execute_link_request(link_request)

        same_name_shared_lib = all_shared_libs_by_name.get(shared_library.name, None)
        if same_name_shared_lib:
          # TODO: test this branch!
          raise self.LinkSharedLibrariesError(
            "The name '{name}' was used for two shared libraries: {prev} and {cur}."
            .format(name=shared_library.name,
                    prev=same_name_shared_lib,
                    cur=shared_library))
        else:
          all_shared_libs_by_name[shared_library.name] = shared_library

        shared_libs_product.add(vt.target, vt.target.target_base).append(shared_library)

  def _retrieve_shared_lib_from_cache(self, vt):
    native_artifact = vt.target.ctypes_native_library
    path_to_cached_lib = os.path.join(
      vt.results_dir, native_artifact.as_shared_lib(self.platform))
    if not os.path.isfile(path_to_cached_lib):
      raise self.LinkSharedLibrariesError("The shared library at {} does not exist!"
                                          .format(path_to_cached_lib))
    return SharedLibrary(name=native_artifact.lib_name, path=path_to_cached_lib)

  def _make_link_request(self,
                         vt,
                         compiled_objects_product,
                         native_target_deps_product,
                         external_libs_product):
    self.context.log.debug("link target: {}".format(vt.target))

    deps = self._retrieve_single_product_at_target_base(native_target_deps_product, vt.target)

    all_compiled_object_files = []

    for dep_tgt in deps:
      self.context.log.debug("dep_tgt: {}".format(dep_tgt))
      object_files = self._retrieve_single_product_at_target_base(compiled_objects_product, dep_tgt)
      self.context.log.debug("object_files: {}".format(object_files))
      object_file_paths = object_files.file_paths()
      self.context.log.debug("object_file_paths: {}".format(object_file_paths))
      all_compiled_object_files.extend(object_file_paths)

    return LinkSharedLibraryRequest.with_external_libs_product(
      linker=self.linker,
      object_files=tuple(all_compiled_object_files),
      native_artifact=vt.target.ctypes_native_library,
      output_dir=vt.results_dir,
      external_libs_product=external_libs_product)

  _SHARED_CMDLINE_ARGS = {
    'darwin': lambda: ['-Wl,-dylib'],
    'linux': lambda: ['-shared'],
  }

  def _get_third_party_lib_args(self, link_request):
    ext_libs = link_request.external_libs_info
    if not ext_libs:
      return []

    return ext_libs.get_third_party_lib_args()

  def _execute_link_request(self, link_request):
    object_files = link_request.object_files

    if len(object_files) == 0:
      raise self.LinkSharedLibrariesError("No object files were provided in request {}!"
                                          .format(link_request))

    linker = link_request.linker
    native_artifact = link_request.native_artifact
    output_dir = link_request.output_dir
    resulting_shared_lib_path = os.path.join(output_dir,
                                             native_artifact.as_shared_lib(self.platform))
    self.context.log.debug("resulting_shared_lib_path: {}".format(resulting_shared_lib_path))
    # We are executing in the results_dir, so get absolute paths for everything.
    cmd = ([linker.exe_filename] +
           self.platform.resolve_platform_specific(self._SHARED_CMDLINE_ARGS) +
           linker.extra_args +
           ['-o', os.path.abspath(resulting_shared_lib_path)] +
           [os.path.abspath(obj) for obj in object_files])
    self.context.log.debug("linker command: {}".format(cmd))

    env = linker.as_invocation_environment_dict
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
        raise self.LinkSharedLibrariesError(
          "Error invoking the native linker with command {cmd} and environment {env} "
          "for request {req}: {err}."
          .format(cmd=cmd, env=env, req=link_request, err=e),
          e)

      rc = process.wait()
      if rc != 0:
        workunit.set_outcome(WorkUnit.FAILURE)
        raise self.LinkSharedLibrariesError(
          "Error linking native objects with command {cmd} and environment {env} "
          "for request {req}. Exit code was: {rc}."
          .format(cmd=cmd, env=env, req=link_request, rc=rc))

    return SharedLibrary(name=native_artifact.lib_name, path=resulting_shared_lib_path)
