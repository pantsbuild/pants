# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.engine.objects import Collection


class CollectionTest(unittest.TestCase):
    def test_collection_iteration(self) -> None:
        self.assertEqual([1, 2], [x for x in Collection([1, 2])])

    def test_collection_bool(self) -> None:
        self.assertTrue(bool(Collection([0])))
        self.assertFalse(bool(Collection([])))
