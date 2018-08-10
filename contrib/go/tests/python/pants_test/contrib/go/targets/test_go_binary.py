# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.contrib.go.targets.go_local_source_test_base import GoLocalSourceTestBase
from pants_test.test_base import TestBase

from pants.contrib.go.targets.go_binary import GoBinary


class GoBinaryTest(GoLocalSourceTestBase, TestBase):

  @property
  def target_type(self):
    return GoBinary
