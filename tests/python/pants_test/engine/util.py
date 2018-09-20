# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
from builtins import str
from types import GeneratorType

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.binaries.binary_util import BinaryUtil
from pants.engine.addressable import addressable_list
from pants.engine.native import Native
from pants.engine.parser import SymbolTable
from pants.engine.scheduler import Scheduler
from pants.engine.selectors import Get
from pants.engine.struct import Struct
from pants.option.global_options import DEFAULT_EXECUTION_OPTIONS
from pants.util.memo import memoized
from pants.util.objects import SubclassesOf
from pants_test.option.util.fakes import create_options_for_optionables
from pants_test.subsystem.subsystem_util import init_subsystem


def run_rule(rule, *args):
  """A test helper function that runs an @rule with a set of arguments and Get providers.

  An @rule named `my_rule` that takes one argument and makes no `Get` requests can be invoked
  like so (although you could also just invoke it directly):
  ```
  return_value = run_rule(my_rule, arg1)
  ```

  In the case of an @rule that makes Get requests, things get more interesting: an extra argument
  is required that represents a dict mapping (product, subject) type pairs to one argument functions
  that take a subject value and return a product value.

  So in the case of an @rule named `my_co_rule` that takes one argument and makes Get requests
  for product and subject types (Listing, Dir), the invoke might look like:
  ```
  return_value = run_rule(my_co_rule, arg1, {(Listing, Dir): lambda x: Listing(..)})
  ```

  :returns: The return value of the completed @rule.
  """

  task_rule = getattr(rule, '_rule', None)
  if task_rule is None:
    raise TypeError('Expected to receive a decorated `@rule`; got: {}'.format(rule))

  gets_len = len(task_rule.input_gets)

  if len(args) != len(task_rule.input_selectors) + (1 if gets_len else 0):
    raise ValueError('Rule expected to receive arguments of the form: {}; got: {}'.format(
      task_rule.input_selectors, args))

  args, get_providers = (args[:-1], args[-1]) if gets_len > 0 else (args, {})
  if gets_len != len(get_providers):
    raise ValueError('Rule expected to receive Get providers for {}; got: {}'.format(
      task_rule.input_gets, get_providers))

  res = rule(*args)
  if not isinstance(res, GeneratorType):
    return res

  def get(product, subject):
    provider = get_providers.get((product, type(subject)))
    if provider is None:
      raise AssertionError('Rule requested: Get{}, which cannot be satisfied.'.format(
        (product, type(subject), subject)))
    return provider(subject)

  rule_coroutine = res
  rule_input = None
  while True:
    res = rule_coroutine.send(rule_input)
    if isinstance(res, Get):
      rule_input = get(res.product, res.subject)
    elif type(res) in (tuple, list):
      rule_input = [get(g.product, g.subject) for g in res]
    else:
      return res


@memoized
def init_native():
  """Initialize and return a `Native` instance."""
  init_subsystem(BinaryUtil.Factory)
  opts = create_options_for_optionables([])
  return Native.create(opts.for_global_scope())


def create_scheduler(rules, validate=True, native=None):
  """Create a Scheduler."""
  native = native or init_native()
  return Scheduler(
    native,
    FileSystemProjectTree(os.getcwd()),
    './.pants.d',
    rules,
    execution_options=DEFAULT_EXECUTION_OPTIONS,
    validate=validate,
  )


class Target(Struct):
  def __init__(self, name=None, configurations=None, **kwargs):
    super(Target, self).__init__(name=name, **kwargs)
    self.configurations = configurations

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
