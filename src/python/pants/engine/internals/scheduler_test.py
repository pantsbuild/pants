# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from contextlib import contextmanager
from dataclasses import dataclass
from textwrap import dedent
from typing import Any

import pytest

from pants.engine.internals.engine_testutil import remove_locations_from_traceback
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import Get, rule
from pants.engine.unions import UnionRule, union
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.testutil.test_base import TestBase


@dataclass(frozen=True)
class A:
    pass


@dataclass(frozen=True)
class B:
    pass


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


# -----------------------------------------------------------------------------------------------
# Test tracebacks.
# -----------------------------------------------------------------------------------------------


def fn_raises():
    raise Exception("An exception!")


@rule(desc="Nested raise")
def nested_raise() -> A:
    fn_raises()
    return A()


def test_trace_includes_rule_exception_traceback() -> None:
    rule_runner = RuleRunner(rules=[nested_raise, QueryRule(A, [])])
    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(A, [])
    normalized_traceback = remove_locations_from_traceback(str(exc.value))
    assert normalized_traceback == dedent(
        f"""\
         1 Exception encountered:

         Engine traceback:
           in select
           in {__name__}.{nested_raise.__name__}
         Traceback (most recent call last):
           File LOCATION-INFO, in nested_raise
             fn_raises()
           File LOCATION-INFO, in fn_raises
             raise Exception(f"An exception!")
         Exception: An exception!
         """
    )


# -----------------------------------------------------------------------------------------------
# Test unhashable types.
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MaybeHashableWrapper:
    maybe_hashable: Any


@rule
async def unhashable(_: MaybeHashableWrapper) -> B:
    return B()


@rule
async def call_unhashable_with_invalid_input() -> C:
    _ = await Get(B, MaybeHashableWrapper([1, 2]))
    return C()


def test_unhashable_types_failure() -> None:
    rule_runner = RuleRunner(
        rules=[
            unhashable,
            call_unhashable_with_invalid_input,
            QueryRule(B, [MaybeHashableWrapper]),
            QueryRule(C, []),
        ]
    )

    # Succeed if an argument to a rule is hashable.
    assert rule_runner.request(B, [MaybeHashableWrapper((1, 2))]) == B()
    # But fail if an argument to a rule is unhashable. This is a TypeError because it fails while
    # hashing as part of FFI.
    with pytest.raises(TypeError, match="unhashable type: 'list'"):
        rule_runner.request(B, [MaybeHashableWrapper([1, 2])])

    # Fail if the `input` in a `Get` is not hashable.
    with pytest.raises(ExecutionError, match="unhashable type: 'list'"):
        rule_runner.request(C, [])
