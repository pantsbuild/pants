# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.cpp.targets.cpp_binary import CppBinary
from pants.contrib.cpp.targets.cpp_library import CppLibrary
from pants.contrib.cpp.tasks.cpp_binary_create import CppBinaryCreate
from pants.contrib.cpp.tasks.cpp_compile import CppCompile
from pants.contrib.cpp.tasks.cpp_library_create import CppLibraryCreate
from pants.contrib.cpp.tasks.cpp_run import CppRun


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'cpp_library': CppLibrary,
      'cpp_binary': CppBinary,
    }
  )


def register_goals():
  task(name='cpp', action=CppCompile).install('compile')
  task(name='cpplib', action=CppLibraryCreate).install('binary')
  task(name='cpp', action=CppBinaryCreate).install('binary')
  task(name='cpp', action=CppRun).install('run')
