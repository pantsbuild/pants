# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast
import unittest
from builtins import object, str

from pants.engine.selectors import Get, Select


class AClass(object):
  pass


class BClass(object):

  def __eq__(self, other):
    return type(self) == type(other)


class SubBClass(BClass):
  pass


class SelectorsTest(unittest.TestCase):
  def test_select_repr(self):
    self.assert_repr("Select(AClass)", Select(AClass))
    self.assert_repr("Select(AClass, optional=True)", Select(AClass, optional=True))

  def assert_repr(self, expected, selector):
    self.assertEqual(expected, repr(selector))


class GetTest(unittest.TestCase):
  def test_create(self):
    # Test the equivalence of the 2-arg and 3-arg versions.
    self.assertEqual(Get(AClass, BClass()),
                     Get(AClass, BClass, BClass()))

    with self.assertRaises(TypeError) as cm:
      Get(AClass, BClass)
    self.assertEqual("""\
The two-argument form of Get does not accept a type as its second argument.

args were: Get(({a!r}, {b!r}))

Get.create_statically_for_rule_graph() should be used to generate a Get() for
the `input_gets` field of a rule. If you are using a `yield Get(...)` in a rule
and a type was intended, use the 3-argument version:
Get({a!r}, {t!r}, {b!r})
""".format(a=AClass, t=type(BClass), b=BClass), str(cm.exception))

    with self.assertRaises(ValueError) as cm:
      Get(1)
    self.assertEqual("Expected either two or three arguments to Get; got (1,).",
                     str(cm.exception))

  def _get_call_node(self, input_string):
    return ast.parse(input_string).body[0].value

  def test_extract_constraints(self):
    parsed_two_arg_call = self._get_call_node("Get(A, B(x))")
    self.assertEqual(('A', 'B'),
                     Get.extract_constraints(parsed_two_arg_call))

    with self.assertRaises(ValueError) as cm:
      Get.extract_constraints(self._get_call_node("Get(1, 2)"))
    self.assertEqual(str(cm.exception), """\
Two arg form of Get expected (product_type, subject_type(subject)), but got: (Num, Num)""")

    parsed_three_arg_call = self._get_call_node("Get(A, B, C(x))")
    self.assertEqual(('A', 'B'),
                      Get.extract_constraints(parsed_three_arg_call))

    with self.assertRaises(ValueError) as cm:
      Get.extract_constraints(self._get_call_node("Get(A, 'asdf', C(x))"))
    self.assertEqual(str(cm.exception), """\
Three arg form of Get expected (product_type, subject_declared_type, subject), but got: (A, Str, Call)""")

  def test_create_statically_for_rule_graph(self):
    self.assertEqual(Get(AClass, BClass, None),
                     Get.create_statically_for_rule_graph(AClass, BClass))
