# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated_module
from pants.task.task import QuietTaskMixin, Task, TaskBase


deprecated_module('0.0.64',
                  hint_message='pants.backend.core.tasks.task has moved to pants.task.task. '
                               'Replace deps on src/python/pants/backend/core/tasks:task and on '
                               'src/python/pants/backend/core/tasks:common with a dep on '
                               'src/python/pants/task and change imports accordingly.')


TaskBase = TaskBase
Task = Task
QuietTaskMixin = QuietTaskMixin
