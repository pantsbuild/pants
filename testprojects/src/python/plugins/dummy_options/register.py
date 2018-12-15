# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from plugins.dummy_options.tasks.dummy_options import DummyOptionsTask

from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
  task(name='dummy-options', action=DummyOptionsTask).install()
