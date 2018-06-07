# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import CppCompiler
from pants.backend.native.subsystems.native_compile_settings import CppCompileSettings
from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_library import CppLibrary
from pants.backend.native.tasks.native_compile import NativeCompile
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.util.contextutil import get_joined_path
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf
from pants.util.process_handler import subprocess


class CppCompile(NativeCompile):

  # Compile only C++ library targets.
  source_target_constraint = SubclassesOf(CppLibrary)

  @classmethod
  def implementation_version(cls):
    return super(CppCompile, cls).implementation_version() + [('CppCompile', 0)]

  class CppCompileError(TaskError): pass

  @classmethod
  def subsystem_dependencies(cls):
    return super(CppCompile, cls).subsystem_dependencies() + (
      CppCompileSettings.scoped(cls),
      NativeToolchain.scoped(cls),
    )

  @memoized_property
  def _toolchain(self):
    return NativeToolchain.scoped_instance(self)

  def get_compile_settings(self):
    return CppCompileSettings.scoped_instance(self)

  def get_compiler(self):
    return self._request_single(CppCompiler, self._toolchain)

  def compile(self, compile_request):
    sources = compile_request.sources
    output_dir = compile_request.output_dir

    if len(sources) == 0:
      self.context.log.debug("no sources for request {}, skipping".format(compile_request))
      return

    cpp_compiler = compile_request.compiler
    err_flags = ['-Werror'] if compile_request.fatal_warnings else []
    # We are going to execute in `output_dir`, so get absolute paths for everything.
    # TODO: If we need to produce static libs, don't add -fPIC! (could use Variants -- see #5788).
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
