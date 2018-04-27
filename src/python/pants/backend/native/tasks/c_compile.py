# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import CCompiler
from pants.backend.native.targets.c_library import CLibrary
from pants.backend.native.tasks.native_compile import NativeCompile, ObjectFiles
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.util.contextutil import get_joined_path
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf, datatype
from pants.util.process_handler import subprocess


class CCompileRequest(datatype([
    'c_compiler',
    'include_dirs',
    'sources',
    'fatal_warnings',
    'output_dir',
])): pass


class CCompile(NativeCompile):

  default_header_file_extensions = ['.h']
  default_source_file_extensions = ['.c']

  @classmethod
  def implementation_version(cls):
    return super(CCompile, cls).implementation_version() + [('CCompile', 0)]

  class CCompileError(TaskError):
    """???"""

  # Compile only C library targets.
  source_target_constraint = SubclassesOf(CLibrary)

  @memoized_property
  def c_compiler(self):
    return self._request_single(CCompiler, self._toolchain)

  # FIXME: note somewhere that this means source file names within a target must be unique (even if
  # the files are in different subdirectories) -- check this at the target level!!!
  def collect_cached_objects(self, versioned_target):
    return ObjectFiles(versioned_target.results_dir, os.listdir(versioned_target.results_dir))

  def compile(self, versioned_target):
    compile_request = self._make_compile_request(versioned_target)
    return self._execute_compile_request(compile_request)

  def _make_compile_request(self, vt):
    include_dirs = self.include_dirs_for_target(vt.target)
    self.context.log.debug("include_dirs: {}".format(include_dirs))
    sources_by_type = self.get_sources_headers_for_target(vt.target)
    fatal_warnings = self.get_task_target_field_value('fatal_warnings', vt.target)
    return CCompileRequest(
      c_compiler=self.c_compiler,
      include_dirs=include_dirs,
      sources=sources_by_type.sources,
      fatal_warnings=fatal_warnings,
      output_dir=vt.results_dir)

  def _execute_compile_request(self, compile_request):
    sources = compile_request.sources
    output_dir = compile_request.output_dir

    if len(sources) == 0:
      # FIXME: do we need this log message? Should we still have it for intentionally header-only
      # libraries (that might be a confusing message to see)?
      self.context.log.debug("no sources in request {}, skipping".format(compile_request))
      return ObjectFiles(output_dir, [])


    # TODO: add -fPIC, but only to object files used for shared libs (how do we determine that?) --
    # alternatively, only allow using native code to build shared libs.
    c_compiler = compile_request.c_compiler
    err_flags = ['-Werror'] if compile_request.fatal_warnings else []
    # We are executing in the results_dir, so get absolute paths for everything.
    # TODO: -fPIC all the time???
    cmd = [c_compiler.exe_filename] + err_flags + ['-c', '-fPIC'] + [
      '-I{}'.format(os.path.abspath(inc_dir)) for inc_dir in compile_request.include_dirs
    ] + [os.path.abspath(src) for src in sources]

    with self.context.new_workunit(name='c-compile', labels=[WorkUnitLabel.COMPILER]) as workunit:
      try:
        process = subprocess.Popen(
          cmd,
          cwd=output_dir,
          stdout=workunit.output('stdout'),
          stderr=workunit.output('stderr'),
          env={'PATH': get_joined_path(c_compiler.path_entries)})
      except OSError as e:
        workunit.set_outcome(WorkUnit.FAILURE)
        raise self.CCompileError(
          "Error invoking the C compiler with command {} for request {}: {}"
          .format(cmd, compile_request, e),
          e)

      rc = process.wait()
      if rc != 0:
        workunit.set_outcome(WorkUnit.FAILURE)
        raise self.CCompileError(
          "Error compiling C sources with command {} for request {}. Exit code was: {}."
          .format(cmd, compile_request, rc))

    # NB: We take everything produced in the output directory without verifying its correctness.
    ret = ObjectFiles(output_dir, os.listdir(output_dir))
    self.context.log.debug("ret: {}".format(ret))
    return ret
