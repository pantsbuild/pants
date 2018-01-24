# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from textwrap import dedent

from pants.build_graph.address import Address
from pants.engine.nodes import Return
from pants.engine.rules import RootRule, TaskRule
from pants.engine.selectors import Select
from pants_test.engine.examples.planners import Classpath, setup_json_scheduler
from pants_test.engine.scheduler_test_base import SchedulerTestBase
from pants_test.engine.util import (assert_equal_with_printing, init_native,
                                    remove_locations_from_traceback)


class EngineTest(unittest.TestCase):

  _native = init_native()

  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.scheduler = setup_json_scheduler(build_root, self._native)

    self.java = Address.parse('src/java/simple')

  def request(self, goals, *addresses):
    return self.scheduler.build_request(goals=goals,
                                        subjects=addresses)

  def test_serial_execution_simple(self):
    request = self.request(['compile'], self.java)
    result = self.scheduler.execute(request)
    self.scheduler.visualize_graph_to_file(request, 'blah/run.0.dot')
    self.assertEqual(Return(Classpath(creator='javac')), result.root_products[0][1])
    self.assertIsNone(result.error)

  def test_product_request_return(self):
    count = 0
    for computed_product in self.scheduler.product_request(Classpath, [self.java]):
      self.assertIsInstance(computed_product, Classpath)
      count += 1
    self.assertGreater(count, 0)


class A(object):
  pass


class B(object):
  pass


class C(object):
  pass


class D(object):
  pass


def fn_raises(x):
  raise Exception('An exception for {}'.format(type(x).__name__))


def nested_raise(x):
  fn_raises(x)


class EngineTraceTest(unittest.TestCase, SchedulerTestBase):

  assert_equal_with_printing = assert_equal_with_printing

  def scheduler(self, rules, include_trace_on_error):
    return self.mk_scheduler(rules=rules, include_trace_on_error=include_trace_on_error)

  def test_no_include_trace_error_raises_boring_error(self):
    rules = [
      RootRule(B),
      TaskRule(A, [Select(B)], nested_raise)
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=False)

    with self.assertRaises(Exception) as cm:
      list(scheduler.product_request(A, subjects=[(B())]))

    self.assert_equal_with_printing('An exception for B', str(cm.exception))

  def test_no_include_trace_error_multiple_paths_raises_executionerror(self):
    rules = [
      RootRule(B),
      TaskRule(A, [Select(B)], nested_raise),
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=False)

    with self.assertRaises(Exception) as cm:
      list(scheduler.product_request(A, subjects=[B(), B()]))

    self.assert_equal_with_printing(dedent('''
      Multiple exceptions encountered:
        Exception: An exception for B
        Exception: An exception for B''').lstrip(),
      str(cm.exception))

  def test_include_trace_error_raises_error_with_trace(self):
    rules = [
      RootRule(B),
      TaskRule(A, [Select(B)], nested_raise)
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=True)
    with self.assertRaises(Exception) as cm:
      list(scheduler.product_request(A, subjects=[(B())]))

    self.assert_equal_with_printing(dedent('''
      Received unexpected Throw state(s):
      Computing Select(<pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =A)
        Computing Task(<function nested_raise at 0xEEEEEEEEE>, <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =A)
          Throw(An exception for B)
            Traceback (most recent call last):
              File LOCATION-INFO, in extern_invoke_runnable
                val = runnable(*args)
              File LOCATION-INFO, in nested_raise
                fn_raises(x)
              File LOCATION-INFO, in fn_raises
                raise Exception('An exception for {}'.format(type(x).__name__))
            Exception: An exception for B
      ''').lstrip()+'\n',
      remove_locations_from_traceback(str(cm.exception)))

  def test_trace_does_not_include_cancellations(self):
    # Tests that when the computation of `Select(C)` fails, the cancellation of `Select(D)`
    # is not rendered as a failure.
    rules = [
      RootRule(B),
      TaskRule(D, [Select(B)], D),
      TaskRule(C, [Select(B)], nested_raise),
      TaskRule(A, [Select(C), Select(D)], A),
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=True)
    with self.assertRaises(Exception) as cm:
      list(scheduler.product_request(A, subjects=[(B())]))

    self.assert_equal_with_printing(dedent('''
      Received unexpected Throw state(s):
      Computing Select(<pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =A)
        Computing Task(<class 'pants_test.engine.test_engine.A'>, <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =A)
          Computing Task(<function nested_raise at 0xEEEEEEEEE>, <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =C)
            Throw(An exception for B)
              Traceback (most recent call last):
                File LOCATION-INFO, in extern_invoke_runnable
                  val = runnable(*args)
                File LOCATION-INFO, in nested_raise
                  fn_raises(x)
                File LOCATION-INFO, in fn_raises
                  raise Exception('An exception for {}'.format(type(x).__name__))
              Exception: An exception for B
      ''').lstrip()+'\n',
      remove_locations_from_traceback(str(cm.exception)))
