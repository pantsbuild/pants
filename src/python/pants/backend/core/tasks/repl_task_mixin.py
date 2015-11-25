# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated_module
from pants.task.repl_task_mixin import ReplTaskMixin


deprecated_module('0.0.64',
                  hint_message='pants.backend.core.tasks.repl_task_mixin has moved to '
                               'pants.task.repl_task_mixin. Replace deps on '
                               'src/python/pants/backend/core/tasks:repl_task_mixin and on with a '
                               'dep on src/python/pants/task and change imports accordingly.')


ReplTaskMixin = ReplTaskMixin
