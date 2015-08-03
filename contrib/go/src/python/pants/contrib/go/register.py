# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_compile import GoCompile
from pants.contrib.go.tasks.go_fetch import GoFetch
from pants.contrib.go.tasks.go_run import GoRun
from pants.contrib.go.tasks.go_setup_workspace import GoSetupWorkspace
from pants.contrib.go.tasks.go_test import GoTest


def build_file_aliases():
  return BuildFileAliases.create(
    targets={
      'go_library': GoLibrary,
      'go_binary': GoBinary,
      'go_remote_library': GoRemoteLibrary,
    }
  )


def register_goals():
  task(name='go', action=GoFetch).install('resolve')
  task(name='go-setup-workspace', action=GoSetupWorkspace).install()
  task(name='go', action=GoCompile).install('compile')
  task(name='go', action=GoRun).install('run')
  task(name='go', action=GoTest).install('test')
