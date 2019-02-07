# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re

from future.utils import PY3, text_type

from pants.engine.objects import Collection
from pants.util.objects import TypeCheckError
from pants_test.test_base import TestBase


class CollectionTest(TestBase):
  def test_collection_iteration(self):
    self.assertEqual([1, 2], [x for x in Collection.of(int)([1, 2])])

  def test_element_typechecking(self):
    IntColl = Collection.of(int)
    with self.assertRaisesRegexp(TypeCheckError, re.escape("""\
field 'dependencies' was invalid: in wrapped constraint TypedCollection(Exactly(int)) matching iterable object [3, {u}'hello']: value {u}'hello' (with type '{string_type}') must satisfy this type constraint: Exactly(int)."""
                                                           .format(u='' if PY3 else 'u',
                                                                   string_type='str' if PY3 else 'unicode'))):
      IntColl([3, "hello"])

    IntOrStringColl = Collection.of(int, text_type)
    self.assertEqual([3, "hello"], [x for x in IntOrStringColl([3, "hello"])])
    with self.assertRaisesRegexp(TypeCheckError, re.escape("""\
field 'dependencies' was invalid: in wrapped constraint TypedCollection(Exactly(int or {string_type})) matching iterable object [()]: value () (with type 'tuple') must satisfy this type constraint: Exactly(int or {string_type})."""
                                                           .format(string_type='str' if PY3 else 'unicode'))):
      IntOrStringColl([()])
