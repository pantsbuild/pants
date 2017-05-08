# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

from pants.engine.addressable import SubclassesOf, addressable_list
from pants.engine.parser import SymbolTable
from pants.engine.rules import RuleIndex
from pants.engine.scheduler import WrappedNativeScheduler
from pants.engine.struct import HasProducts, Struct
from pants.engine.subsystem.native import Native
from pants_test.subsystem.subsystem_util import init_subsystem


def init_native():
  """Initialize and return the `Native` subsystem."""
  init_subsystem(Native.Factory)
  return Native.Factory.global_instance().create()


def create_native_scheduler(root_subject_types, rules):
  """Create a WrappedNativeScheduler, with an initialized native instance."""
  rule_index = RuleIndex.create(rules)
  native = init_native()
  scheduler = WrappedNativeScheduler(native, '.', './.pants.d', [], rule_index, root_subject_types)
  return scheduler


class Target(Struct, HasProducts):
  def __init__(self, name=None, configurations=None, **kwargs):
    super(Target, self).__init__(name=name, **kwargs)
    self.configurations = configurations

  @property
  def products(self):
    return self.configurations

  @addressable_list(SubclassesOf(Struct))
  def configurations(self):
    pass


class TargetTable(SymbolTable):
  @classmethod
  def table(cls):
    return {'struct': Struct, 'target': Target}


def assert_equal_with_printing(test_case, expected, actual):
  """Asserts equality, but also prints the values so they can be compared on failure.

  Usage:

     class FooTest(unittest.TestCase):
       assert_equal_with_printing = assert_equal_with_printing

       def test_foo(self):
         self.assert_equal_with_printing("a", "b")
  """
  str_actual = str(actual)
  print('Expected:')
  print(expected)
  print('Actual:')
  print(str_actual)
  test_case.assertEqual(expected, str_actual)


def remove_locations_from_traceback(trace):
  location_pattern = re.compile('"/.*", line \d+')
  address_pattern = re.compile('0x[0-9a-f]+')
  new_trace = location_pattern.sub('LOCATION-INFO', trace)
  new_trace = address_pattern.sub('0xEEEEEEEEE', new_trace)
  return new_trace
