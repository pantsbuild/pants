# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import unittest
from builtins import object, str
from textwrap import dedent

from pants.build_graph.address import Address
from pants.engine.nodes import Return
from pants.engine.rules import RootRule, TaskRule, rule
from pants.engine.scheduler import ExecutionError
from pants.engine.selectors import Get, Select
from pants.util.contextutil import temporary_dir
from pants.util.objects import datatype
from pants_test.engine.examples.planners import Classpath, setup_json_scheduler
from pants_test.engine.scheduler_test_base import SchedulerTestBase
from pants_test.engine.util import (assert_equal_with_printing, init_native,
                                    remove_locations_from_traceback)


class EngineExamplesTest(unittest.TestCase):

  _native = init_native()

  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.scheduler = setup_json_scheduler(build_root, self._native)

    self.java = Address.parse('src/java/simple')

  def request(self, products, *addresses):
    return self.scheduler.execution_request(products, addresses)

  def test_serial_execution_simple(self):
    request = self.request([Classpath], self.java)
    result = self.scheduler.execute(request)
    with temporary_dir() as tempdir:
      self.scheduler.visualize_graph_to_file(os.path.join(tempdir, 'run.0.dot'))
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


class Fib(datatype([('val', int)])): pass


@rule(Fib, [Select(int)])
def fib(n):
  if n < 2:
    yield Fib(n)
  x, y = yield Get(Fib, int(n-2)), Get(Fib, int(n-1))
  yield Fib(x.val + y.val)


class EngineTest(unittest.TestCase, SchedulerTestBase):

  assert_equal_with_printing = assert_equal_with_printing

  def scheduler(self, rules, include_trace_on_error):
    return self.mk_scheduler(rules=rules, include_trace_on_error=include_trace_on_error)

  def test_recursive_multi_get(self):
    # Tests that a rule that "uses itself" multiple times per invoke works.
    rules = [
      fib,
      RootRule(int),
    ]

    fib_10, = self.mk_scheduler(rules=rules).product_request(Fib, subjects=[10])

    self.assertEqual(55, fib_10.val)

  def test_no_include_trace_error_raises_boring_error(self):
    rules = [
      RootRule(B),
      TaskRule(A, [Select(B)], nested_raise)
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=False)

    with self.assertRaises(ExecutionError) as cm:
      list(scheduler.product_request(A, subjects=[(B())]))

    self.assert_equal_with_printing('1 Exception encountered:\n  Exception: An exception for B', str(cm.exception))

  def test_no_include_trace_error_multiple_paths_raises_executionerror(self):
    rules = [
      RootRule(B),
      TaskRule(A, [Select(B)], nested_raise),
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=False)

    with self.assertRaises(ExecutionError) as cm:
      list(scheduler.product_request(A, subjects=[B(), B()]))

    self.assert_equal_with_printing(dedent('''
      2 Exceptions encountered:
        Exception: An exception for B
        Exception: An exception for B''').lstrip(),
      str(cm.exception))

  def test_include_trace_error_raises_error_with_trace(self):
    rules = [
      RootRule(B),
      TaskRule(A, [Select(B)], nested_raise)
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=True)
    with self.assertRaises(ExecutionError) as cm:
      list(scheduler.product_request(A, subjects=[(B())]))

    self.assert_equal_with_printing(dedent('''
      1 Exception encountered:
      Computing Select(<pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =A)
        Computing Task(nested_raise, <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =A)
          Throw(An exception for B)
            Traceback (most recent call last):
              File LOCATION-INFO, in call
                val = func(*args)
              File LOCATION-INFO, in nested_raise
                fn_raises(x)
              File LOCATION-INFO, in fn_raises
                raise Exception('An exception for {}'.format(type(x).__name__))
            Exception: An exception for B
      ''').lstrip()+'\n',
      remove_locations_from_traceback(str(cm.exception)))

  def test_trace_multi(self):
    # Tests that when multiple distinct failures occur, they are each rendered.
    rules = [
      RootRule(B),
      TaskRule(D, [Select(B)], nested_raise),
      TaskRule(C, [Select(B)], nested_raise),
      TaskRule(A, [Select(C), Select(D)], A),
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=True)
    with self.assertRaises(ExecutionError) as cm:
      list(scheduler.product_request(A, subjects=[(B())]))

    self.assert_equal_with_printing(dedent('''
      1 Exception encountered:
      Computing Select(<pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =A)
        Computing Task(A, <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =A)
          Computing Task(nested_raise, <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =D)
            Throw(An exception for B)
              Traceback (most recent call last):
                File LOCATION-INFO, in call
                  val = func(*args)
                File LOCATION-INFO, in nested_raise
                  fn_raises(x)
                File LOCATION-INFO, in fn_raises
                  raise Exception('An exception for {}'.format(type(x).__name__))
              Exception: An exception for B


      Computing Select(<pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =A)
        Computing Task(A, <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =A)
          Computing Task(nested_raise, <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =C)
            Throw(An exception for B)
              Traceback (most recent call last):
                File LOCATION-INFO, in call
                  val = func(*args)
                File LOCATION-INFO, in nested_raise
                  fn_raises(x)
                File LOCATION-INFO, in fn_raises
                  raise Exception('An exception for {}'.format(type(x).__name__))
              Exception: An exception for B
      ''').lstrip()+'\n',
      remove_locations_from_traceback(str(cm.exception)))

  def test_illegal_root_selection(self):
    rules = [
      RootRule(B),
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=False)

    # No rules are available to compute A.
    with self.assertRaises(Exception) as cm:
      list(scheduler.product_request(A, subjects=[(B())]))

    self.assert_equal_with_printing('No installed rules can satisfy Select(A) for a root subject of type B.', str(cm.exception))
