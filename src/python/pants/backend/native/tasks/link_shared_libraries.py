# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import Linker, Platform
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.native.tasks.native_compile import ObjectFiles
from pants.backend.native.tasks.native_task import NativeTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.task.task import Task
from pants.util.contextutil import get_joined_path
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf, datatype
from pants.util.process_handler import subprocess


class SharedLibrary(datatype(['name', 'path'])): pass


class LinkSharedLibraryRequest(datatype([
    'linker',
    'object_files',
    'native_artifact',
    'output_dir',
])): pass


class LinkSharedLibraries(NativeTask):

  @classmethod
  def product_types(cls):
    return [SharedLibrary]

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require(ObjectFiles)

  @property
  def cache_target_dirs(self):
    return True

  @classmethod
  def implementation_version(cls):
    return super(LinkSharedLibraries, cls).implementation_version() + [('LinkSharedLibraries', 0)]

  class LinkSharedLibrariesError(TaskError):
    """???"""

  @memoized_property
  def linker(self):
    return self._request_single(Linker, self._toolchain)

  def execute(self):
    targets_providing_artifacts = self.context.targets(NativeLibrary.provides_native_artifact)
    compiled_objects_product = self.context.products.get(ObjectFiles)
    shared_libs_product = self.context.products.get(SharedLibrary)

    with self.invalidated(targets_providing_artifacts,
                          invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.all_vts:
        if vt.valid:
          shared_library = self._retrieve_shared_lib_from_cache(vt)
        else:
          link_request = self._make_link_request(vt, compiled_objects_product)
          shared_library = self._execute_link_request(link_request)

        # FIXME: de-dup libs by name? just disallow it i think
        shared_libs_product.add(vt.target, vt.target.target_base).append(shared_library)

  def _retrieve_shared_lib_from_cache(self, vt):
    native_artifact = vt.target.provides
    path_to_cached_lib = os.path.join(vt.results_dir, native_artifact.as_filename(self.linker.platform))
    # TODO: check if path exists!!
    return SharedLibrary(name=native_artifact.lib_name, path=path_to_cached_lib)

  def _make_link_request(self, vt, compiled_objects_product):
    # FIXME: should coordinate to ensure we get the same deps for link and compile (could put that
    # in the ObjectFiles type tbh)
    deps = self.native_deps(vt.target)

    all_compiled_object_files = []

    for dep_tgt in deps:
      product_mapping = compiled_objects_product.get(dep_tgt)
      base_dirs = product_mapping.keys()
      assert(len(base_dirs) == 1)
      single_base_dir = base_dirs[0]
      object_files_list = product_mapping[single_base_dir]
      assert(len(object_files_list) == 1)
      single_product = object_files_list[0]
      object_files_for_target = single_product.file_paths()
      self.context.log.debug("single_product: {}, object_files_for_target: {}, target: {}"
                             .format(single_product, object_files_for_target, vt.target))
      # TODO: dedup object file paths? can we assume they are already deduped?
      all_compiled_object_files.extend(object_files_for_target)

    return LinkSharedLibraryRequest(
      linker=self.linker,
      object_files=all_compiled_object_files,
      native_artifact=vt.target.provides,
      output_dir=vt.results_dir)

  _SHARED_CMDLINE_ARGS = {
    'darwin': lambda: ['-dylib'],
    'linux': lambda: ['-shared'],
  }

  def _get_shared_lib_cmdline_args(self):
    return self.linker.platform.resolve_platform_specific(self._SHARED_CMDLINE_ARGS)

  def _execute_link_request(self, link_request):
    object_files = link_request.object_files

    if len(object_files) == 0:
      # TODO: there's a legitimate reason to have no object files, but we don't support that yet (we
      # need to expand LinkSharedLibraryRequest)
      raise self.LinkSharedLibrariesError(
        "no object files were provided in request {} -- this is not yet supported"
        .format(link_request))

    linker = link_request.linker
    native_artifact = link_request.native_artifact
    output_dir = link_request.output_dir
    resulting_shared_lib_path = os.path.join(output_dir, native_artifact.as_filename(linker.platform))
    # We are executing in the results_dir, so get absolute paths for everything.
    cmd = ([linker.exe_filename] +
           self._get_shared_lib_cmdline_args() +
           ['-o', os.path.abspath(resulting_shared_lib_path)] +
           [os.path.abspath(obj) for obj in object_files])

    with self.context.new_workunit(name='link-shared-libraries',
                                   labels=[WorkUnitLabel.LINKER]) as workunit:
      try:
        process = subprocess.Popen(
          cmd,
          cwd=output_dir,
          stdout=workunit.output('stdout'),
          stderr=workunit.output('stderr'),
          env={'PATH': get_joined_path(linker.path_entries)})
      except OSError as e:
        workunit.set_outcome(WorkUnit.FAILURE)
        raise self.LinkSharedLibrariesError(
          "Error invoking the native linker with command {} for request {}: {}"
          .format(cmd, link_request, e),
          e)

      rc = process.wait()
      if rc != 0:
        workunit.set_outcome(WorkUnit.FAILURE)
        raise self.LinkSharedLibrariesError(
          "Error linking native objects with command {} for request {}. Exit code was: {}."
          .format(cmd, link_request, rc))

    return SharedLibrary(name=native_artifact.lib_name, path=resulting_shared_lib_path)
