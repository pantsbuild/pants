# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.findbugs.tasks.findbugs import FindBugs


def register_goals():
  Goal.register('findbugs', 'Check Java code for FindBugs violations.')
  task(name='findbugs', action=FindBugs).install('compile')
