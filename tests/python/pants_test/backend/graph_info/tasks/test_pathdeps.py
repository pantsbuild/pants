# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.graph_info.tasks.pathdeps import PathDeps
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class TestPathDeps(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return PathDeps

  def test_filter_targets(self):
    self.add_to_build_file(
        'BUILD',
         'target(name="a")\n'
    )
    self.add_to_build_file(
        'second/BUILD',
         'target(name="b")\n'
    )
    a = self.target('//:a')
    b = self.target('//second:b')
    c = self.make_target('c', synthetic=True)
    targets = [a, b, c]

    output = self.execute_console_task(targets=targets)
    self.assertEqual(2, len(output))
