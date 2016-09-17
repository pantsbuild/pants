# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.goal.task_registrar import TaskRegistrar as task
from pants.task.task import Task


def register_goals():
  task(name='do-some-work', action=TestWorkUnitTask).install()


class TestWorkUnitTask(NailgunTask):
  @classmethod
  def register_options(cls, register):
    register('--do-nothing', default=False, type=bool)

  def execute(self):
    # This run is going to fail.
    if self.get_options().do_nothing:
      return

    self.runjava(
      classpath=[],
      main='non.existent.main.class',
    )
