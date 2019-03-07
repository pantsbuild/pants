# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.deprecated import deprecated_module
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.findbugs.tasks.findbugs import FindBugs


deprecated_module(
    '1.18.0.dev2',
    hint_message='The findbugs module is deprecated in favor of the errorprone module.'
  )


def register_goals():
  task(name='findbugs', action=FindBugs).install('compile')
