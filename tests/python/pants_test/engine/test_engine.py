# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager
from textwrap import dedent

from pants.build_graph.address import Address
from pants.engine.engine import LocalSerialEngine
from pants.engine.nodes import Return
from pants.engine.rules import TaskRule
from pants.engine.scheduler import ExecutionRequest
from pants.engine.selectors import Select
from pants_test.engine.examples.planners import Classpath, setup_json_scheduler
from pants_test.engine.util import (assert_equal_with_printing, create_native_scheduler,
                                    init_native, remove_locations_from_traceback)


class EngineTest(unittest.TestCase):

  _native = init_native()

  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.scheduler = setup_json_scheduler(build_root, self._native)

    self.java = Address.parse('src/java/simple')

  def request(self, goals, *addresses):
    return self.scheduler.build_request(goals=goals,
                                        subjects=addresses)

  def assert_engine(self, engine):
    result = engine.execute(self.request(['compile'], self.java))
    self.scheduler.visualize_graph_to_file('blah/run.0.dot')
    self.assertEqual([Return(Classpath(creator='javac'))], result.root_products.values())
    self.assertIsNone(result.error)

  @contextmanager
  def serial_engine(self):
    yield LocalSerialEngine(self.scheduler)

  def test_serial_engine_simple(self):
    with self.serial_engine() as engine:
      self.assert_engine(engine)

  def test_product_request_return(self):
    with self.serial_engine() as engine:
      count = 0
      for computed_product in engine.product_request(Classpath, [self.java]):
        self.assertIsInstance(computed_product, Classpath)
        count += 1
      self.assertGreater(count, 0)


class A(object):
  pass


class B(object):
  pass


def fn_raises(x):
  raise Exception('An exception for {}'.format(type(x).__name__))


def nested_raise(x):
  fn_raises(x)


class SimpleScheduler(object):
  def __init__(self, native_scheduler):
    self._scheduler = native_scheduler

  def trace(self):
    for line in self._scheduler.graph_trace():
      yield line

  def execution_request(self, products, subjects):
    return ExecutionRequest(tuple((s, Select(p)) for s in subjects for p in products))

  def schedule(self, execution_request):
    self._scheduler.exec_reset()
    for subject, selector in execution_request.roots:
      self._scheduler.add_root_selection(subject, selector)
    self._scheduler.run_and_return_stat()

  def root_entries(self, execution_request):
    return self._scheduler.root_entries(execution_request)


class EngineTraceTest(unittest.TestCase):

  assert_equal_with_printing = assert_equal_with_printing

  def scheduler(self, root_subject_types, rules):
    return SimpleScheduler(
      create_native_scheduler(root_subject_types, rules))

  def test_no_include_trace_error_raises_boring_error(self):
    rules = [
      TaskRule(A, [Select(B)], nested_raise)
    ]

    engine = self.create_engine({B},
                                rules,
                                include_trace_on_error=False)

    with self.assertRaises(Exception) as cm:
      list(engine.product_request(A, subjects=[(B())]))

    self.assert_equal_with_printing('An exception for B', str(cm.exception))

  def create_engine(self, root_subject_types, rules, include_trace_on_error):
    engine = LocalSerialEngine(self.scheduler(root_subject_types, rules), include_trace_on_error=include_trace_on_error)
    return engine

  def test_no_include_trace_error_multiple_paths_raises_executionerror(self):
    rules = [
      TaskRule(A, [Select(B)], nested_raise),
    ]

    engine = self.create_engine({B},
                                rules,
                                include_trace_on_error=False)

    with self.assertRaises(Exception) as cm:
      list(engine.product_request(A, subjects=[B(), B()]))

    self.assert_equal_with_printing(dedent('''
      Multiple exceptions encountered:
        Exception: An exception for B
        Exception: An exception for B''').lstrip(),
      str(cm.exception))


  def test_include_trace_error_raises_error_with_trace(self):
    rules = [
      TaskRule(A, [Select(B)], nested_raise)
    ]

    engine = self.create_engine({B},
                                rules,
                                include_trace_on_error=True)
    with self.assertRaises(Exception) as cm:
      list(engine.product_request(A, subjects=[(B())]))

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
