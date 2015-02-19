# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.binary_create import BinaryCreate
from pants_test.task_test_base import TaskTestBase


sample_ini_test_1 = """
[DEFAULT]
pants_distdir = /tmp/dist
"""


class BinaryCreateTest(TaskTestBase):
  def task_type(cls):
    return BinaryCreate

  def test_binary_create_init(self):
    binary_create = self.create_task(self.context(config=sample_ini_test_1), '/tmp/workdir')
    self.assertEquals(binary_create._outdir, '/tmp/dist')
