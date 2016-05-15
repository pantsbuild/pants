# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.findbugs.tasks.findbugs import FindBugs


class FindBugsTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return FindBugs

  def test_no_sources(self):
    task = self.create_task(self.context())
    self.assertEqual(None, task.execute())
