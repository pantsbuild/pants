# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.engine.objects import Collection
from pants_test.test_base import TestBase


class CollectionTest(TestBase):
  def test_collection_iteration(self):
    self.assertEqual([1, 2], [x for x in Collection.of(int)([1, 2])])
