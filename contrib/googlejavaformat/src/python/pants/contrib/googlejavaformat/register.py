# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.googlejavaformat.googlejavaformat import (GoogleJavaFormat,
                                                             GoogleJavaFormatCheckFormat)


def register_goals():
  task(name='google-java-format', action=GoogleJavaFormat).install('fmt')
  task(name='google-java-format', action=GoogleJavaFormatCheckFormat).install('lint')
