# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from contextlib import contextmanager
from dataclasses import dataclass
from textwrap import dedent
from typing import Any

from pants.engine.internals.engine_testutil import (
    assert_equal_with_printing,
    remove_locations_from_traceback,
)
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import Get, rule
from pants.engine.unions import UnionRule, union
from pants.testutil.rule_runner import QueryRule
from pants.testutil.test_base import TestBase


@dataclass(frozen=True)
class A:
    pass


@dataclass(frozen=True)
class B:
    pass


def fn_raises(x):
    raise Exception(f"An exception for {type(x).__name__}")


@rule(desc="Nested raise")
def nested_raise(b: B) -> A:
    fn_raises(b)
    return A()


@rule
def consumes_a_and_b(a: A, b: B) -> str:
    return str(f"{a} and {b}")


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
async def transitive_coroutine_rule(c: C) -> D:
    b = await Get(B, C, c)
    return D(b)


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
    @staticmethod
    def a() -> A:
        return A()


@rule
def select_union_a(union_a: UnionA) -> A:
    return union_a.a()


class UnionB:
    @staticmethod
    def a() -> A:
        return A()


@rule
def select_union_b(union_b: UnionB) -> A:
    return union_b.a()


# TODO: add MultiGet testing for unions!
@rule
async def a_union_test(union_wrapper: UnionWrapper) -> A:
    union_a = await Get(A, UnionBase, union_wrapper.inner)
    return union_a


class UnionX:
    pass


@rule
async def error_msg_test_rule(union_wrapper: UnionWrapper) -> UnionX:
    # NB: We install a UnionRule to make UnionWrapper a member of this union, but then we pass the
    # inner value, which is _not_ registered.
    _ = await Get(A, UnionWithNonMemberErrorMsg, union_wrapper.inner)
    raise AssertionError("The statement above this one should have failed!")


class TypeCheckFailWrapper:
    """This object wraps another object which will be used to demonstrate a type check failure when
    the engine processes an `await Get(...)` statement."""

    def __init__(self, inner):
        self.inner = inner


@rule
async def a_typecheck_fail_test(wrapper: TypeCheckFailWrapper) -> A:
    # This `await` would use the `nested_raise` rule, but it won't get to the point of raising since
    # the type check will fail at the Get.
    _ = await Get(A, B, wrapper.inner)  # noqa: F841
    return A()


@dataclass(frozen=True)
class CollectionType:
    # NB: We pass an unhashable type when we want this to fail at the root, and a hashable type
    # when we'd like it to succeed.
    items: Any


@rule
async def c_unhashable(_: CollectionType) -> C:
    # This `await` would use the `nested_raise` rule, but it won't get to the point of raising since
    # the hashability check will fail.
    _result = await Get(A, B, list())  # noqa: F841
    return C()


@rule
def boolean_and_int(i: int, b: bool) -> A:
    return A()


@contextmanager
def assert_execution_error(test_case, expected_msg):
    with test_case.assertRaises(ExecutionError) as cm:
        yield
    test_case.assertIn(expected_msg, remove_locations_from_traceback(str(cm.exception)))


class SchedulerTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            consumes_a_and_b,
            QueryRule(str, (A, B)),
            transitive_b_c,
            QueryRule(str, (A, C)),
            transitive_coroutine_rule,
            QueryRule(D, (C,)),
            UnionRule(UnionBase, UnionA),
            UnionRule(UnionWithNonMemberErrorMsg, UnionWrapper),
            select_union_a,
            UnionRule(union_base=UnionBase, union_member=UnionB),
            select_union_b,
            a_union_test,
            QueryRule(A, (UnionWrapper,)),
            error_msg_test_rule,
            QueryRule(UnionX, (UnionWrapper,)),
            boolean_and_int,
            QueryRule(A, (int, bool)),
        )

    def test_use_params(self):
        # Confirm that we can pass in Params in order to provide multiple inputs to an execution.
        a, b = A(), B()
        result_str = self.request(str, [a, b])
        self.assertEqual(result_str, consumes_a_and_b(a, b))

        # And confirm that a superset of Params is also accepted.
        result_str = self.request(str, [a, b, self])
        self.assertEqual(result_str, consumes_a_and_b(a, b))

        # But not a subset.
        expected_msg = "No installed QueryRules can compute str given input Params(A), but"
        with self.assertRaisesRegex(Exception, re.escape(expected_msg)):
            self.request(str, [a])

    def test_transitive_params(self):
        # Test that C can be provided and implicitly converted into a B with transitive_b_c() to satisfy
        # the selectors of consumes_a_and_b().
        a, c = A(), C()
        result_str = self.request(str, [a, c])
        self.assertEqual(
            remove_locations_from_traceback(result_str),
            remove_locations_from_traceback(consumes_a_and_b(a, transitive_b_c(c))),
        )

        # Test that an inner Get in transitive_coroutine_rule() is able to resolve B from C due to
        # the existence of transitive_b_c().
        self.request(D, [c])

    def test_consumed_types(self):
        assert {A, B, C, str} == set(
            self.scheduler.scheduler.rule_graph_consumed_types([A, C], str)
        )

    def test_strict_equals(self):
        # With the default implementation of `__eq__` for boolean and int, `1 == True`. But in the
        # engine that behavior would be surprising, and would cause both of these Params to intern
        # to the same value, triggering an error. Instead, the engine additionally includes the
        # type of a value in equality.
        assert A() == self.request(A, [1, True])

    @contextmanager
    def _assert_execution_error(self, expected_msg):
        with assert_execution_error(self, expected_msg):
            yield

    def test_union_rules(self):
        self.request(A, [UnionWrapper(UnionA())])
        self.request(A, [UnionWrapper(UnionB())])
        # Fails due to no union relationship from A -> UnionBase.
        with self._assert_execution_error("Type A is not a member of the UnionBase @union"):
            self.request(A, [UnionWrapper(A())])

    def test_union_rules_no_docstring(self):
        with self._assert_execution_error("specific error message for UnionA instance"):
            self.request(UnionX, [UnionWrapper(UnionA())])


class SchedulerWithNestedRaiseTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            a_typecheck_fail_test,
            c_unhashable,
            nested_raise,
            QueryRule(A, (TypeCheckFailWrapper,)),
            QueryRule(A, (B,)),
            QueryRule(C, (CollectionType,)),
        )

    def test_get_type_match_failure(self):
        """Test that Get(...)s are now type-checked during rule execution, to allow for union
        types."""

        with self.assertRaises(ExecutionError) as cm:
            # `a_typecheck_fail_test` above expects `wrapper.inner` to be a `B`.
            self.request(A, [TypeCheckFailWrapper(A())])

        expected_regex = "WithDeps.*did not declare a dependency on JustGet"
        self.assertRegex(str(cm.exception), expected_regex)

    def test_unhashable_root_params_failure(self):
        """Test that unhashable root params result in a structured error."""
        # This will fail at the rust boundary, before even entering the engine.
        with self.assertRaisesRegex(TypeError, "unhashable type: 'list'"):
            self.request(C, [CollectionType([1, 2, 3])])

    def test_unhashable_get_params_failure(self):
        """Test that unhashable Get(...) params result in a structured error."""
        # This will fail inside of `c_unhashable_dataclass`.
        with self.assertRaisesRegex(ExecutionError, "unhashable type: 'list'"):
            self.request(C, [CollectionType(tuple())])

    def test_trace_includes_rule_exception_traceback(self):
        # Execute a request that will trigger the nested raise, and then directly inspect its trace.
        request = self.scheduler.execution_request([A], [B()])
        _, throws = self.scheduler.execute(request)

        with self.assertRaises(ExecutionError) as cm:
            self.scheduler._raise_on_error([t for _, t in throws])

        trace = remove_locations_from_traceback(str(cm.exception))
        assert_equal_with_printing(
            self,
            dedent(
                f"""\
                 1 Exception encountered:

                 Engine traceback:
                   in select
                   in {self.__module__}.{nested_raise.__name__}
                 Traceback (most recent call last):
                   File LOCATION-INFO, in nested_raise
                     fn_raises(b)
                   File LOCATION-INFO, in fn_raises
                     raise Exception(f"An exception for {{type(x).__name__}}")
                 Exception: An exception for B
                 """
            ),
            trace,
        )
