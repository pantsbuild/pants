# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import CppCompiler
from pants.backend.native.targets.cpp_library import CppLibrary
from pants.backend.native.tasks.native_compile import NativeCompile, ObjectFiles
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.util.contextutil import get_joined_path
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf, datatype
from pants.util.process_handler import subprocess


class CppCompileRequest(datatype([
    'cpp_compiler',
    'include_dirs',
    'sources',
    'fatal_warnings',
    'output_dir',
])): pass


class CppCompile(NativeCompile):

  default_header_file_extensions = ['.h', '.hpp', '.tpp']
  default_source_file_extensions = ['.cpp', '.cxx', '.cc']

  @classmethod
  def implementation_version(cls):
    return super(CppCompile, cls).implementation_version() + [('CppCompile', 0)]

  class CppCompileError(TaskError):
    """???"""

  source_target_constraint = SubclassesOf(CppLibrary)

  @memoized_property
  def cpp_compiler(self):
    return self._request_single(CppCompiler, self._toolchain)

  # FIXME: note somewhere that this means source file names within a target must be unique -- check
  # this at the target level!!!
  def collect_cached_objects(self, versioned_target):
    return ObjectFiles(versioned_target.results_dir, os.listdir(versioned_target.results_dir))

  def compile(self, versioned_target):
    compile_request = self._make_compile_request(versioned_target)
    return self._execute_compile_request(compile_request)

  def _make_compile_request(self, vt):
    include_dirs = self.include_dirs_for_target(vt.target)
    sources_by_type = self.get_sources_headers_for_target(vt.target)
    fatal_warnings = self.get_task_target_field_value('fatal_warnings', vt.target)
    return CppCompileRequest(
      cpp_compiler=self.cpp_compiler,
      include_dirs=include_dirs,
      sources=sources_by_type.sources,
      fatal_warnings=fatal_warnings,
      output_dir=vt.results_dir)

  def _execute_compile_request(self, compile_request):
    sources = compile_request.sources
    output_dir = compile_request.output_dir

    if len(sources) == 0:
      self.context.log.debug("no sources for request {}, skipping".format(compile_request))
      return ObjectFiles(output_dir, [])

    cpp_compiler = compile_request.cpp_compiler
    err_flags = ['-Werror'] if compile_request.fatal_warnings else []
    # We are executing in the results_dir, so get absolute paths for everything.
    # TODO: -fPIC all the time???
    cmd = [cpp_compiler.exe_filename] + err_flags + ['-c', '-fPIC'] + [
      '-I{}'.format(os.path.abspath(inc_dir)) for inc_dir in compile_request.include_dirs
    ] + [os.path.abspath(src) for src in sources]

    with self.context.new_workunit(name='cpp-compile', labels=[WorkUnitLabel.COMPILER]) as workunit:
      try:
        process = subprocess.Popen(
          cmd,
          cwd=output_dir,
          stdout=workunit.output('stdout'),
          stderr=workunit.output('stderr'),
          env={'PATH': get_joined_path(cpp_compiler.path_entries)})
      except OSError as e:
        workunit.set_outcome(WorkUnit.FAILURE)
        raise self.CppCompileError(
          "Error invoking the C++ compiler with command {} for request {}: {}"
          .format(cmd, compile_request, e),
          e)

      rc = process.wait()
      if rc != 0:
        workunit.set_outcome(WorkUnit.FAILURE)
        raise self.CppCompileError(
          "Error compiling C++ sources with command {} for request {}. Exit code was: {}."
          .format(cmd, compile_request, rc))

    # NB: We take everything produced in the output directory without verifying its correctness.
    return ObjectFiles(output_dir, os.listdir(output_dir))
