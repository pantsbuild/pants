# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.backend.core.tasks.task import Task
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir

from pants.contrib.cpp.targets.cpp_binary import CppBinary
from pants.contrib.cpp.targets.cpp_library import CppLibrary
from pants.contrib.cpp.targets.cpp_target import CppTarget
from pants.contrib.cpp.toolchain.cpp_toolchain import CppToolchain


class CppTask(Task):
  @staticmethod
  def is_cpp(target):
    return isinstance(target, CppTarget)

  @staticmethod
  def is_library(target):
    return isinstance(target, CppLibrary)

  @staticmethod
  def is_binary(target):
    return isinstance(target, CppBinary)

  @classmethod
  def register_options(cls, register):
    super(CppTask, cls).register_options(register)
    register('--compiler',
             help='Set a specific compiler to use (eg, g++-4.8, clang++)')
    register('--cc-options',
             help='Append these options to the compiler command line.')
    register('--cc-extensions',
             default=['cc', 'cxx', 'cpp'],
             help=('The list of extensions (without the .) to consider when '
                   'determining if a file is a C++ source file.'))

  def compile_sources(self, target):
    """Compile all sources in a given target to object files."""

    def is_cc(source):
      _, ext = os.path.splitext(source)
      return ext[1:] in self.get_options().cc_extensions

    objs = []

    if self.is_cpp(target):
      # TODO: consider MULTITOOL to enclose the loop over N compiles
      for source in target.sources_relative_to_buildroot():
        if is_cc(source):
          # TODO: Parallelise the compilation.
          # TODO: Only recompile source files that have changed since the
          #       object file was last written. Also use the output from
          #       gcc -M to track dependencies on headers.
          obj = self._compile(target, source)
          objs.extend([obj])

    return objs

  def _compile(self, target, source):
    """Compile given source to an object file."""
    abs_source_root = os.path.join(get_buildroot(), target.target_base)
    abs_source = os.path.join(get_buildroot(), source)
    rel_source = os.path.relpath(abs_source, abs_source_root)
    root, _ = os.path.splitext(rel_source)
    obj_name = root + '.o'

    obj = os.path.join(self.workdir, target.id, obj_name)

    safe_mkdir(os.path.dirname(obj))

    # TODO: include dir should include dependent work dir when headers are copied there.
    include_dirs = []
    for dep in target.dependencies:
      if self.is_library(dep):
        include_dirs.extend([os.path.join(get_buildroot(), dep.target_base)])

    cmd = [self.cpp_toolchain.compiler]
    cmd.extend(['-c'])
    cmd.extend(('-I{0}'.format(i) for i in include_dirs))
    cmd.extend(['-o' + obj, abs_source])
    if self.get_options().cc_options != None:
      cmd.extend([self.get_options().cc_options])

    # TODO: submit_async_work with self.run_command, [(cmd)] as a Work object.
    with self.context.new_workunit(name='cpp-compile', labels=[WorkUnit.COMPILER]):
      self.run_command(cmd)

    return obj

  def run_command(self, cmd):
    try:
      self.context.log.debug('Executing: {0}'.format(cmd))
      # TODO: capture stdout/stderr and redirect to log
      subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
      raise TaskError('Execution failed: {0}'.format(e))
    except:
      raise TaskError('Failed to execute {0}'.format(cmd))

  @property
  def cpp_toolchain(self):
    return CppToolchain(self.get_options().compiler)
