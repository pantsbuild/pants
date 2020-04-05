# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Thrift code generator.

See https://github.com/twitter/scrooge.
"""

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.scrooge.tasks.scrooge_gen import ScroogeGen
from pants.contrib.scrooge.tasks.thrift_linter_task import ThriftLinterTask


def register_goals():
    task(name="thrift", action=ThriftLinterTask).install("lint")
    task(name="scrooge", action=ScroogeGen).install("gen")
