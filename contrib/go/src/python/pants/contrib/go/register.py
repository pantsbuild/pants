# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.build_file_aliases import BuildFileAliases, Macro
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
  return BuildFileAliases.create(
    # We register all Go targets anonymously so that only the macros below can create them in
    # BUILD files.  This allows us to exert more control over allowable parameters and in
    # particular disallow specifying target names; instead we control the name to always match
    # the BUILD file location and strictly enforce 1:1:1 in local source targets and
    # single-version for remote dependencies with multiple packages.
    anonymous_targets=[
      GoBinary,
      GoLibrary,
      GoRemoteLibrary,
    ],
    context_aware_object_factories={
      GoBinary.alias(): Macro.wrap(GoBinary.create, GoBinary),
      GoLibrary.alias(): Macro.wrap(GoLibrary.create, GoLibrary),
      'go_remote_libraries': Macro.wrap(GoRemoteLibrary.from_packages, GoRemoteLibrary),
      'go_remote_library': Macro.wrap(GoRemoteLibrary.from_package, GoRemoteLibrary),
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
