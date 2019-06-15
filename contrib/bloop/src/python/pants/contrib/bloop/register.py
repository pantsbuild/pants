# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.bloop.tasks.bloop_gen import BloopGen


def register_goals():
  task(name='bloop-gen', action=BloopGen).install('bloop')
