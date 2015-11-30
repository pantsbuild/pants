# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.coverage.base import Coverage
from pants_test.backend.jvm.tasks.jvm_binary_task_test_base import JvmBinaryTaskTestBase


class TestBase(JvmBinaryTaskTestBase):

  @classmethod
  def task_type(cls):
    return Coverage
