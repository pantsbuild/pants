# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.core_tasks.changed_target_tasks import CompileChanged, TestChanged
from pants.core_tasks.clean import Clean
from pants.core_tasks.invalidate import Invalidate
from pants.core_tasks.noop import NoopCompile, NoopTest
from pants.core_tasks.reporting_server_kill import ReportingServerKill
from pants.core_tasks.reporting_server_run import ReportingServerRun
from pants.core_tasks.roots import ListRoots
from pants.core_tasks.run_prep_command import RunPrepCommand
from pants.core_tasks.what_changed import WhatChanged
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
  # Cleaning.
  task(name='invalidate', action=Invalidate).install()
  task(name='clean-all', action=Clean).install()

  # Reporting server.
  # TODO: The reporting server should be subsumed into pantsd, and not run via a task.
  task(name='server', action=ReportingServerRun, serialize=False).install()
  task(name='killserver', action=ReportingServerKill, serialize=False).install()

  # Stub for other goals to schedule 'compile'. See noop_exec_task.py for why this is useful.
  task(name='compile', action=NoopCompile).install('compile')

  # Must be the first thing we register under 'test'.
  task(name='run_prep_command', action=RunPrepCommand).install('test')
  # Stub for other goals to schedule 'test'. See noop_exec_task.py for why this is useful.
  task(name='test', action=NoopTest).install('test')

  # Operations on files that the SCM detects as changed.
  task(name='changed', action=WhatChanged).install()
  task(name='compile-changed', action=CompileChanged).install()
  task(name='test-changed', action=TestChanged).install()

  # Workspace information.
  task(name='roots', action=ListRoots).install()
