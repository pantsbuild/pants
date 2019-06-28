# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

from pants.engine.objects import Collection
from pants.util.objects import TypeCheckError
from pants_test.test_base import TestBase


class CollectionTest(TestBase):
  def test_collection_iteration(self):
    self.assertEqual([1, 2], [x for x in Collection.of(int)([1, 2])])

  def test_element_typechecking(self):
    IntColl = Collection.of(int)
    with self.assertRaisesRegexp(TypeCheckError, re.escape(
      "field 'dependencies' was invalid: in wrapped constraint TypedCollection(Exactly(int)) "
      "matching iterable object [3, 'hello']: value 'hello' (with type 'str') must satisfy this "
      "type constraint: Exactly(int).")):
      IntColl([3, "hello"])

    IntOrStringColl = Collection.of(int, str)
    self.assertEqual([3, "hello"], [x for x in IntOrStringColl([3, "hello"])])
    with self.assertRaisesRegexp(TypeCheckError, re.escape(
      "field 'dependencies' was invalid: in wrapped constraint TypedCollection(Exactly(int or "
      "str)) matching iterable object [()]: value () (with type 'tuple') must satisfy this type "
      "constraint: Exactly(int or str).""")):
      IntOrStringColl([()])

  def test_collection_bool(self):
    self.assertTrue(bool(Collection.of(int)([0])))
    self.assertFalse(bool(Collection.of(int)([])))
