# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.core_tasks.changed_target_tasks import CompileChanged, TestChanged
from pants.core_tasks.noop import NoopCompile, NoopTest
from pants.core_tasks.what_changed import WhatChanged
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
  task(name='changed', action=WhatChanged).install()

  # Stub for other goals to schedule 'compile'. See noop_exec_task.py for why this is useful.
  task(name='compile', action=NoopCompile).install('compile')
  task(name='compile-changed', action=CompileChanged).install()

  # Stub for other goals to schedule 'test'. See noop_exec_task.py for why this is useful.
  task(name='test', action=NoopTest).install('test')
  task(name='test-changed', action=TestChanged).install()
