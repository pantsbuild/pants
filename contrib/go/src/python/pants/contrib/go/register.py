# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_binary_create import GoBinaryCreate
from pants.contrib.go.tasks.go_buildgen import GoBuildgen
from pants.contrib.go.tasks.go_compile import GoCompile
from pants.contrib.go.tasks.go_fetch import GoFetch
from pants.contrib.go.tasks.go_run import GoRun
from pants.contrib.go.tasks.go_test import GoTest


def build_file_aliases():
  return BuildFileAliases(
    targets={
      GoBinary.alias(): TargetMacro.Factory.wrap(GoBinary.create, GoBinary),
      GoLibrary.alias(): TargetMacro.Factory.wrap(GoLibrary.create, GoLibrary),
      'go_remote_libraries': TargetMacro.Factory.wrap(GoRemoteLibrary.from_packages,
                                                      GoRemoteLibrary),
      'go_remote_library': TargetMacro.Factory.wrap(GoRemoteLibrary.from_package, GoRemoteLibrary),
    }
  )


def register_goals():
  task(name='go', action=GoBuildgen).install('buildgen').with_description(
    'Automatically generate BUILD files.')
  task(name='go', action=GoFetch).install('resolve')
  task(name='go', action=GoCompile).install('compile')
  task(name='go', action=GoBinaryCreate).install('binary')
  task(name='go', action=GoRun).install('run')
  task(name='go', action=GoTest).install('test')
