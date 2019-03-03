# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re
import unittest
from builtins import object, str
from contextlib import contextmanager
from textwrap import dedent

from pants.engine.rules import RootRule, UnionRule, rule, union
from pants.engine.scheduler import ExecutionError
from pants.engine.selectors import Get, Params, Select
from pants.util.objects import datatype
from pants_test.engine.util import (assert_equal_with_printing, create_scheduler,
                                    remove_locations_from_traceback)
from pants_test.test_base import TestBase


class A(object):
  pass


class B(object):
  pass


def fn_raises(x):
  raise Exception('An exception for {}'.format(type(x).__name__))


@rule(A, [Select(B)])
def nested_raise(x):
  fn_raises(x)


@rule(str, [Select(A), Select(B)])
def consumes_a_and_b(a, b):
  return str('{} and {}'.format(a, b))


class C(object):
  pass


@rule(B, [Select(C)])
def transitive_b_c(c):
  return B()


class D(datatype([('b', B)])):
  pass


@rule(D, [Select(C)])
def transitive_coroutine_rule(c):
  b = yield Get(B, C, c)
  yield D(b)


@union
class UnionBase(object): pass


class UnionWrapper(object):
  def __init__(self, inner):
    self.inner = inner


class UnionA(object):

  def a(self):
    return A()


@rule(A, [Select(UnionA)])
def select_union_a(union_a):
  return union_a.a()


class UnionB(object):

  def a(self):
    return A()


@rule(A, [Select(UnionB)])
def select_union_b(union_b):
  return union_b.a()


# TODO: add GetMulti testing for unions!
@rule(A, [Select(UnionWrapper)])
def a_union_test(union_wrapper):
  union_a = yield Get(A, UnionBase, union_wrapper.inner)
  yield union_a


class TypeCheckFailWrapper(object):
  """
  This object wraps another object which will be used to demonstrate a type check failure when the
  engine processes a `yield Get(...)` statement.
  """

  def __init__(self, inner):
    self.inner = inner


@rule(A, [Select(TypeCheckFailWrapper)])
def a_typecheck_fail_test(wrapper):
  # This `yield Get(A, B, ...)` will use the `nested_raise` rule defined above, but it won't get to
  # the point of raising since the type check will fail at the Get.
  supposedly_a = yield Get(A, B, wrapper.inner)
  yield supposedly_a


class SchedulerTest(TestBase):

  @classmethod
  def rules(cls):
    return super(SchedulerTest, cls).rules() + [
      RootRule(A),
      # B is both a RootRule and an intermediate product here.
      RootRule(B),
      RootRule(C),
      consumes_a_and_b,
      transitive_b_c,
      transitive_coroutine_rule,
      RootRule(UnionWrapper),
      UnionRule(UnionBase, UnionA),
      RootRule(UnionA),
      select_union_a,
      UnionRule(union_base=UnionBase, union_member=UnionB),
      RootRule(UnionB),
      select_union_b,
      a_union_test,
      a_typecheck_fail_test,
      RootRule(TypeCheckFailWrapper),
    ]

  def test_use_params(self):
    # Confirm that we can pass in Params in order to provide multiple inputs to an execution.
    a, b = A(), B()
    result_str, = self.scheduler.product_request(str, [Params(a, b)])
    self.assertEquals(result_str, consumes_a_and_b(a, b))

    # And confirm that a superset of Params is also accepted.
    result_str, = self.scheduler.product_request(str, [Params(a, b, self)])
    self.assertEquals(result_str, consumes_a_and_b(a, b))

    # But not a subset.
    expected_msg = ("No installed @rules can satisfy Select({}) for input Params(A)"
                    .format(str.__name__))
    with self.assertRaisesRegexp(Exception, re.escape(expected_msg)):
      self.scheduler.product_request(str, [Params(a)])

  def test_transitive_params(self):
    # Test that C can be provided and implicitly converted into a B with transitive_b_c() to satisfy
    # the selectors of consumes_a_and_b().
    a, c = A(), C()
    result_str, = self.scheduler.product_request(str, [Params(a, c)])
    self.assertEquals(remove_locations_from_traceback(result_str),
                      remove_locations_from_traceback(consumes_a_and_b(a, transitive_b_c(c))))

    # Test that an inner Get in transitive_coroutine_rule() is able to resolve B from C due to the
    # existence of transitive_b_c().
    result_d, = self.scheduler.product_request(D, [Params(c)])
    # We don't need the inner B objects to be the same, and we know the arguments are type-checked,
    # we're just testing transitively resolving products in this file.
    self.assertTrue(isinstance(result_d, D))

  @contextmanager
  def _assert_execution_error(self, expected_msg):
    # TODO(#7303): use self.assertRaisesWithMessageContaining()!
    with self.assertRaises(ExecutionError) as cm:
      yield
    self.assertIn(expected_msg, remove_locations_from_traceback(str(cm.exception)))

  def test_union_rules(self):
    a, = self.scheduler.product_request(A, [Params(UnionWrapper(UnionA()))])
    # TODO: figure out what to assert here!
    self.assertTrue(isinstance(a, A))
    a, = self.scheduler.product_request(A, [Params(UnionWrapper(UnionB()))])
    self.assertTrue(isinstance(a, A))
    # Fails due to no union relationship from A -> UnionBase.
    expected_msg = """\
Exception: WithDeps(Inner(InnerEntry { params: {UnionWrapper}, rule: Task(Task { product: TypeConstraint(Exactly(A)), clause: [Select { product: Exactly(UnionWrapper) }], gets: [Get { product: TypeConstraint(Exactly(A)), subject: UnionA }, Get { product: TypeConstraint(Exactly(A)), subject: UnionB }], func: Function(<function a_union_test at 0xEEEEEEEEE>), cacheable: true }) })) did not declare a dependency on JustGet(Get { product: TypeConstraint(Exactly(A)), subject: A })
"""
    with self._assert_execution_error(expected_msg):
      self.scheduler.product_request(A, [Params(UnionWrapper(A()))])

  def test_get_type_match_failure(self):
    """Test that Get(...)s are now type-checked during rule execution, to allow for union types."""
    expected_msg = """\
Exception: WithDeps(Inner(InnerEntry { params: {TypeCheckFailWrapper}, rule: Task(Task { product: TypeConstraint(Exactly(A)), clause: [Select { product: Exactly(TypeCheckFailWrapper) }], gets: [Get { product: TypeConstraint(Exactly(A)), subject: B }], func: Function(<function a_typecheck_fail_test at 0xEEEEEEEEE>), cacheable: true }) })) did not declare a dependency on JustGet(Get { product: TypeConstraint(Exactly(A)), subject: A })
"""
    with self._assert_execution_error(expected_msg):
      # `a_typecheck_fail_test` above expects `wrapper.inner` to be a `B`.
      self.scheduler.product_request(A, [Params(TypeCheckFailWrapper(A()))])


class SchedulerTraceTest(unittest.TestCase):
  assert_equal_with_printing = assert_equal_with_printing

  def test_trace_includes_rule_exception_traceback(self):
    rules = [
      RootRule(B),
      nested_raise,
    ]

    scheduler = create_scheduler(rules)
    request = scheduler._native.new_execution_request()
    subject = B()
    scheduler.add_root_selection(request, subject, A)
    session = scheduler.new_session()
    scheduler._run_and_return_roots(session._session, request)

    trace = '\n'.join(scheduler.graph_trace(request))
    # NB removing location info to make trace repeatable
    trace = remove_locations_from_traceback(trace)

    assert_equal_with_printing(self, dedent('''
                     Computing Select(<pants_test.engine.test_scheduler.B object at 0xEEEEEEEEE>, Exactly(A))
                       Computing Task(nested_raise, <pants_test.engine.test_scheduler.B object at 0xEEEEEEEEE>, Exactly(A), true)
                         Throw(An exception for B)
                           Traceback (most recent call last):
                             File LOCATION-INFO, in call
                               val = func(*args)
                             File LOCATION-INFO, in nested_raise
                               fn_raises(x)
                             File LOCATION-INFO, in fn_raises
                               raise Exception('An exception for {}'.format(type(x).__name__))
                           Exception: An exception for B''').lstrip() + '\n\n', # Traces include two empty lines after.
                               trace)
