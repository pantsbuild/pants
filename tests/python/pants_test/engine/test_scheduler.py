# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
import sys
import unittest.mock
from contextlib import contextmanager
from dataclasses import dataclass
from textwrap import dedent
from typing import List

from pants.engine.native import Native
from pants.engine.rules import RootRule, UnionRule, rule, union
from pants.engine.scheduler import ExecutionError, SchedulerSession
from pants.engine.selectors import Get, Params
from pants_test.engine.util import assert_equal_with_printing, remove_locations_from_traceback
from pants_test.test_base import TestBase


@dataclass(frozen=True)
class A:
  pass


@dataclass(frozen=True)
class B:
  pass


def fn_raises(x):
  raise Exception(f'An exception for {type(x).__name__}')


@rule
def nested_raise(x: B) -> A:
  fn_raises(x)


@rule
def consumes_a_and_b(a: A, b: B) -> str:
  return str('{} and {}'.format(a, b))


@dataclass(frozen=True)
class C:
  pass


@rule
def transitive_b_c(c: C) -> B:
  return B()


@dataclass(frozen=True)
class D:
  b: B


@rule
def transitive_coroutine_rule(c: C) -> D:
  b = yield Get(B, C, c)
  yield D(b)


@union
class UnionBase:
  pass


@union
class UnionWithNonMemberErrorMsg:

  @staticmethod
  def non_member_error_message(subject):
    return f"specific error message for {type(subject).__name__} instance"


class UnionWrapper:
  def __init__(self, inner):
    self.inner = inner


class UnionA:

  def a(self):
    return A()


@rule
def select_union_a(union_a: UnionA) -> A:
  return union_a.a()


class UnionB:

  def a(self):
    return A()


@rule
def select_union_b(union_b: UnionB) -> A:
  return union_b.a()


# TODO: add GetMulti testing for unions!
@rule
def a_union_test(union_wrapper: UnionWrapper) -> A:
  union_a = yield Get(A, UnionBase, union_wrapper.inner)
  yield union_a


class UnionX:
  pass


@rule
def error_msg_test_rule(union_wrapper: UnionWrapper) -> UnionX:
  union_x = yield Get(UnionX, UnionWithNonMemberErrorMsg, union_wrapper.inner)
  yield union_x


class TypeCheckFailWrapper:
  """
  This object wraps another object which will be used to demonstrate a type check failure when the
  engine processes a `yield Get(...)` statement.
  """

  def __init__(self, inner):
    self.inner = inner


@rule
def a_typecheck_fail_test(wrapper: TypeCheckFailWrapper) -> A:
  # This `yield` would use the `nested_raise` rule, but it won't get to the point of raising since
  # the type check will fail at the Get.
  _ = yield Get(A, B, wrapper.inner) # noqa: F841
  yield A()


@rule
def c_unhashable(_: TypeCheckFailWrapper) -> C:
  # This `yield` would use the `nested_raise` rule, but it won't get to the point of raising since
  # the hashability check will fail.
  _ = yield Get(A, B, list()) # noqa: F841
  yield C()


@dataclass(frozen=True)
class CollectionType:
  items: List[int]


@rule
def c_unhashable_dataclass(_: CollectionType) -> C:
  # This `yield` would use the `nested_raise` rule, but it won't get to the point of raising since
  # the hashability check will fail.
  _ = yield Get(A, B, list()) # noqa: F841
  yield C()


@contextmanager
def assert_execution_error(test_case, expected_msg):
  with test_case.assertRaises(ExecutionError) as cm:
    yield
  test_case.assertIn(expected_msg, remove_locations_from_traceback(str(cm.exception)))


class SchedulerTest(TestBase):

  @classmethod
  def rules(cls):
    return super().rules() + [
      RootRule(A),
      # B is both a RootRule and an intermediate product here.
      RootRule(B),
      RootRule(C),
      RootRule(UnionX),
      error_msg_test_rule,
      consumes_a_and_b,
      transitive_b_c,
      transitive_coroutine_rule,
      RootRule(UnionWrapper),
      UnionRule(UnionBase, UnionA),
      UnionRule(UnionWithNonMemberErrorMsg, UnionX),
      RootRule(UnionA),
      select_union_a,
      UnionRule(union_base=UnionBase, union_member=UnionB),
      RootRule(UnionB),
      select_union_b,
      a_union_test,
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
    expected_msg = ("No installed @rules can compute {} for input Params(A), but"
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
    with assert_execution_error(self, expected_msg):
      yield

  def test_union_rules(self):
    a, = self.scheduler.product_request(A, [Params(UnionWrapper(UnionA()))])
    # TODO: figure out what to assert here!
    self.assertTrue(isinstance(a, A))
    a, = self.scheduler.product_request(A, [Params(UnionWrapper(UnionB()))])
    self.assertTrue(isinstance(a, A))
    # Fails due to no union relationship from A -> UnionBase.
    expected_msg = """\
Type A is not a member of the UnionBase @union
"""
    with self._assert_execution_error(expected_msg):
      self.scheduler.product_request(A, [Params(UnionWrapper(A()))])

  def test_union_rules_no_docstring(self):
    expected_msg = "specific error message for UnionA instance"
    with self._assert_execution_error(expected_msg):
      self.scheduler.product_request(UnionX, [Params(UnionWrapper(UnionA()))])


class SchedulerWithNestedRaiseTest(TestBase):

  @classmethod
  def rules(cls):
    return super().rules() + [
      RootRule(B),
      RootRule(TypeCheckFailWrapper),
      RootRule(CollectionType),
      a_typecheck_fail_test,
      c_unhashable,
      c_unhashable_dataclass,
      nested_raise,
    ]

  def test_get_type_match_failure(self):
    """Test that Get(...)s are now type-checked during rule execution, to allow for union types."""
    expected_msg = """\
Exception: WithDeps(Inner(InnerEntry { params: {TypeCheckFailWrapper}, rule: Task(Task { product: A, clause: [Select { product: TypeCheckFailWrapper }], gets: [Get { product: A, subject: B }], func: a_typecheck_fail_test(), cacheable: true }) })) did not declare a dependency on JustGet(Get { product: A, subject: A })
"""
    with assert_execution_error(self, expected_msg):
      # `a_typecheck_fail_test` above expects `wrapper.inner` to be a `B`.
      self.scheduler.product_request(A, [Params(TypeCheckFailWrapper(A()))])

  def test_unhashable_failure(self):
    """Test that unhashable Get(...) params result in a structured error."""

    def assert_has_cffi_extern_traceback_header(exc_str):
      self.assertTrue(exc_str.startswith(dedent("""\
        1 Exception raised in CFFI extern methods:
        Traceback (most recent call last):
        """)), "exc_str was: {}".format(exc_str))

    def assert_has_end_of_cffi_extern_error_traceback(exc_str):
      self.assertIn(dedent("""\
        Traceback (most recent call last):
          File LOCATION-INFO, in extern_identify
            return c.identify(obj)
          File LOCATION-INFO, in identify
            hash_ = hash(obj)
          File "<string>", line 2, in __hash__
        TypeError: unhashable type: 'list'
        """), exc_str, "exc_str was: {}".format(exc_str))

    resulting_engine_error = dedent("""\
        Exception: Types that will be passed as Params at the root of a graph need to be registered via RootRule:
          Any\n\n\n""")

    # Test that the error contains the full traceback from within the CFFI context as well
    # (mentioning which specific extern method ended up raising the exception).
    with self.assertRaises(ExecutionError) as cm:
      self.scheduler.product_request(C, [Params(CollectionType([1, 2, 3]))])
    exc_str = remove_locations_from_traceback(str(cm.exception))
    # TODO: convert these manual self.assertTrue() conditionals to a self.assertStartsWith() method
    # in TestBase!
    assert_has_cffi_extern_traceback_header(exc_str)
    assert_has_end_of_cffi_extern_error_traceback(exc_str)
    self.assertIn(dedent("""\
      The engine execution request raised this error, which is probably due to the errors in the
      CFFI extern methods listed above, as CFFI externs return None upon error:
      """), exc_str)
    self.assertTrue(exc_str.endswith(resulting_engine_error), "exc_str was: {}".format(exc_str))

    PATCH_OPTS = dict(autospec=True, spec_set=True)
    def create_cffi_exception():
      try:
        raise Exception('test cffi exception')
      except:                   # noqa: T803
        return Native.CFFIExternMethodRuntimeErrorInfo(*sys.exc_info()[0:3])

    # Test that CFFI extern method errors result in an ExecutionError, even if .execution_request()
    # succeeds.
    with self.assertRaises(ExecutionError) as cm:
      with unittest.mock.patch.object(SchedulerSession, 'execution_request',
                             **PATCH_OPTS) as mock_exe_request:
        with unittest.mock.patch.object(Native, '_peek_cffi_extern_method_runtime_exceptions',
                               **PATCH_OPTS) as mock_cffi_exceptions:
          mock_exe_request.return_value = None
          mock_cffi_exceptions.return_value = [create_cffi_exception()]
          self.scheduler.product_request(C, [Params(CollectionType([1, 2, 3]))])
    exc_str = remove_locations_from_traceback(str(cm.exception))
    assert_has_cffi_extern_traceback_header(exc_str)
    self.assertIn("Exception: test cffi exception", exc_str)
    self.assertNotIn(resulting_engine_error, exc_str)

    # Test that an error in the .execution_request() method is propagated directly, even if there
    # are no CFFI extern methods.
    class TestError(Exception): pass
    with self.assertRaisesWithMessage(TestError, 'non-CFFI error'):
      with unittest.mock.patch.object(SchedulerSession, 'execution_request',
                             **PATCH_OPTS) as mock_exe_request:
        mock_exe_request.side_effect = TestError('non-CFFI error')
        self.scheduler.product_request(C, [Params(CollectionType([1, 2, 3]))])

  def test_trace_includes_rule_exception_traceback(self):
    # Execute a request that will trigger the nested raise, and then directly inspect its trace.
    request = self.scheduler.execution_request([A], [B()])
    self.scheduler.execute(request)

    trace = remove_locations_from_traceback('\n'.join(self.scheduler.trace(request)))
    assert_equal_with_printing(self, dedent('''
                     Computing Select(B(), A)
                       Computing Task(nested_raise(), B(), A, true)
                         Throw(An exception for B)
                           Traceback (most recent call last):
                             File LOCATION-INFO, in call
                               val = func(*args)
                             File LOCATION-INFO, in nested_raise
                               fn_raises(x)
                             File LOCATION-INFO, in fn_raises
                               raise Exception(f'An exception for {type(x).__name__}')
                           Exception: An exception for B''').lstrip() + '\n\n',  # Traces include two empty lines after.
                               trace)
