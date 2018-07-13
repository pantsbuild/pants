# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.scrooge.tasks.scrooge_gen import ScroogeGen
from pants.contrib.scrooge.tasks.thrift_linter import ThriftLinter


def register_goals():
  task(name='thrift', action=ThriftLinter).install('lint')
  task(name='scrooge', action=ScroogeGen).install('gen')
