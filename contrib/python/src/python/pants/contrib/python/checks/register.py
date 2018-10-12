# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.python.checks.tasks.checkstyle.checkstyle import Checkstyle
from pants.contrib.python.checks.tasks.python_eval import PythonEval


def register_goals():
  task(name='python-eval', action=PythonEval).install('lint')
  task(name='pythonstyle', action=Checkstyle).install('lint')
