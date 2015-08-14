# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import subprocess

from pants.backend.core.tasks.task import Task
from pants.base.exceptions import TaskError

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
    register('--compiler', advanced=True, fingerprint=True,
             help='Set a specific compiler to use (eg, g++-4.8, clang++)')

  def execute(self):
    raise NotImplementedError('execute must be implemented by subclasses of CppTask')

  def run_command(self, cmd, workunit):
    try:
      self.context.log.debug('Executing: {0}'.format(cmd))
      # TODO: capture stdout/stderr and redirect to log
      subprocess.check_call(cmd, stdout=workunit.output('stdout'), stderr=workunit.output('stderr'))
    except subprocess.CalledProcessError as e:
      raise TaskError('Execution failed: {0}'.format(e))
    except:
      raise TaskError('Failed to execute {0}'.format(cmd))

  @property
  def cpp_toolchain(self):
    return CppToolchain(self.get_options().compiler)
