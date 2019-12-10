# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from dataclasses import dataclass, field
from textwrap import dedent
from typing import List

from pants.engine.rules import RootRule, rule
from pants.engine.scheduler import ExecutionError
from pants.engine.selectors import Get, MultiGet
from pants.reporting.streaming_workunit_handler import StreamingWorkunitHandler
from pants.testutil.engine.util import assert_equal_with_printing, remove_locations_from_traceback
from pants_test.engine.scheduler_test_base import SchedulerTestBase


class A:
  pass


class B:
  pass


class C:
  pass


class D:
  pass


def fn_raises(x):
  raise Exception(f'An exception for {type(x).__name__}')


@rule
def nested_raise(x: B) -> A:
  fn_raises(x)


@dataclass(frozen=True)
class Fib:
  val: int


@rule(name="fib")
async def fib(n: int) -> Fib:
  if n < 2:
    return Fib(n)
  x, y = tuple(await MultiGet([Get(Fib, int(n-2)), Get(Fib, int(n-1))]))
  return Fib(x.val + y.val)


@dataclass(frozen=True)
class MyInt:
  val: int


@dataclass(frozen=True)
class MyFloat:
  val: float


@rule
def upcast(n: MyInt) -> MyFloat:
  return MyFloat(float(n.val))


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
      nested_raise,
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=False)

    with self.assertRaises(ExecutionError) as cm:
      list(scheduler.product_request(A, subjects=[(B())]))

    self.assert_equal_with_printing('1 Exception encountered:\n  Exception: An exception for B', str(cm.exception))

  def test_no_include_trace_error_multiple_paths_raises_executionerror(self):
    rules = [
      RootRule(B),
      nested_raise,
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
      nested_raise,
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=True)
    with self.assertRaises(ExecutionError) as cm:
      list(scheduler.product_request(A, subjects=[(B())]))

    self.assert_equal_with_printing(dedent('''
      1 Exception encountered:
      Computing Select(<pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, A)
        Computing Task(nested_raise(), <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, A, true)
          Throw(An exception for B)
            Traceback (most recent call last):
              File LOCATION-INFO, in call
                val = func(*args)
              File LOCATION-INFO, in nested_raise
                fn_raises(x)
              File LOCATION-INFO, in fn_raises
                raise Exception(f'An exception for {type(x).__name__}')
            Exception: An exception for B
      ''').lstrip()+'\n',
      remove_locations_from_traceback(str(cm.exception)))

  def test_fork_context(self):
    # A smoketest that confirms that we can successfully enter and exit the fork context, which
    # implies acquiring and releasing all relevant Engine resources.
    expected = "42"
    def fork_context_body():
      return expected
    res = self.mk_scheduler().with_fork_context(fork_context_body)
    self.assertEquals(res, expected)

  @unittest.skip('Inherently flaky as described in https://github.com/pantsbuild/pants/issues/6829')
  def test_trace_multi(self):
    # Tests that when multiple distinct failures occur, they are each rendered.

    @rule
    def d_from_b_nested_raise(b: B) -> D:
      fn_raises(b)

    @rule
    def c_from_b_nested_raise(b: B) -> C:
      fn_raises(b)

    @rule
    def a_from_c_and_d(c: C, d: D) -> A:
      return A()

    rules = [
      RootRule(B),
      d_from_b_nested_raise,
      c_from_b_nested_raise,
      a_from_c_and_d,
    ]

    scheduler = self.scheduler(rules, include_trace_on_error=True)
    with self.assertRaises(ExecutionError) as cm:
      list(scheduler.product_request(A, subjects=[(B())]))

    self.assert_equal_with_printing(dedent('''
      1 Exception encountered:
      Computing Select(<pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, A)
        Computing Task(a_from_c_and_d(), <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, A, true)
          Computing Task(d_from_b_nested_raise(), <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =D, true)
            Throw(An exception for B)
              Traceback (most recent call last):
                File LOCATION-INFO, in call
                  val = func(*args)
                File LOCATION-INFO, in d_from_b_nested_raise
                  fn_raises(b)
                File LOCATION-INFO, in fn_raises
                  raise Exception('An exception for {}'.format(type(x).__name__))
              Exception: An exception for B


      Computing Select(<pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, A)
        Computing Task(a_from_c_and_d(), <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, A, true)
          Computing Task(c_from_b_nested_raise(), <pants_test.engine.test_engine.B object at 0xEEEEEEEEE>, =C, true)
            Throw(An exception for B)
              Traceback (most recent call last):
                File LOCATION-INFO, in call
                  val = func(*args)
                File LOCATION-INFO, in c_from_b_nested_raise
                  fn_raises(b)
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

    self.assert_equal_with_printing('No installed @rules can compute A for input Params(B).', str(cm.exception))

  def test_non_existing_root_fails_differently(self):
    rules = [
      upcast,
    ]

    with self.assertRaises(Exception) as cm:
      list(self.mk_scheduler(rules=rules, include_trace_on_error=False))

    self.assert_equal_with_printing(dedent('''
      Rules with errors: 1
        (MyFloat, [MyInt], upcast()):
          No rule was available to compute MyInt. Maybe declare it as a RootRule(MyInt)?
        ''').strip(),
      str(cm.exception)
    )

  def test_async_reporting(self):
    rules = [ fib, RootRule(int)]
    scheduler = self.mk_scheduler(rules, include_trace_on_error=False, should_report_workunits=True)

    @dataclass
    class Tracker:
      workunits: List[dict] = field(default_factory=list)

      def add(self, workunits) -> None:
        self.workunits.extend(workunits)

    tracker = Tracker()
    async_reporter = StreamingWorkunitHandler(scheduler, callbacks=[tracker.add], report_interval_seconds=0.01)
    with async_reporter.session():
      scheduler.product_request(Fib, subjects=[0])

    # The execution of the single named @rule "fib" should be providing this one workunit.
    self.assertEquals(len(tracker.workunits), 1)

    tracker.workunits = []
    with async_reporter.session():
      scheduler.product_request(Fib, subjects=[10])

    # Requesting a bigger fibonacci number will result in more rule executions and thus more reported workunits.
    # In this case, we expect 10 invocations of the `fib` rule.
    self.assertEquals(len(tracker.workunits), 10)
