# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.graph_info.tasks.pathdeps import PathDeps
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class TestPathDeps(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return PathDeps

  def test_filter_targets(self):
    self.add_to_build_file(
        'BUILD',
         'target(name="a")'
    )
    self.add_to_build_file(
        'second/BUILD',
         'target(name="b")'
    )
    a = self.target('//:a')
    b = self.target('//second:b')
    c = self.make_target('c', synthetic=True)
    targets = [a, b, c]

    self.assert_console_output(
        os.path.join(self.build_root, 'second'),
        self.build_root,
        targets=targets
    )
