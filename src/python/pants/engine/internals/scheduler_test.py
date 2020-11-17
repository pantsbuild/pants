# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from textwrap import dedent
from typing import Any

import pytest

from pants.engine.internals.engine_testutil import remove_locations_from_traceback
from pants.engine.internals.engine_testutil import (
    assert_equal_with_printing,
    remove_locations_from_traceback,
)
from pants.engine.internals.native import IncorrectProductError
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import Get, rule
from pants.engine.unions import UnionRule, union
from pants.testutil.rule_runner import QueryRule, RuleRunner

# -----------------------------------------------------------------------------------------------
# Test params
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class A:
    pass


@dataclass(frozen=True)
class B:
    pass


@rule
def consumes_a_and_b(a: A, b: B) -> str:
    return str(f"{a} and {b}")


def test_use_params() -> None:
    rule_runner = RuleRunner(rules=[consumes_a_and_b, QueryRule(str, [A, B])])
    # Confirm that we can pass in Params in order to provide multiple inputs to an execution.
    a, b = A(), B()
    result_str = rule_runner.request(str, [a, b])
    assert result_str == consumes_a_and_b(a, b)

    # And confirm that a superset of Params is also accepted.
    result_str = rule_runner.request(str, [a, b, b"bytes aren't used by any rules"])
    assert result_str == consumes_a_and_b(a, b)

    # But not a subset.
    expected_msg = "No installed QueryRules can compute str given input Params(A), but"
    with pytest.raises(Exception, match=re.escape(expected_msg)):
        rule_runner.request(str, [a])


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


@pytest.fixture
def transitive_params_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            consumes_a_and_b,
            QueryRule(str, [A, B]),
            transitive_b_c,
            QueryRule(str, [A, C]),
            transitive_coroutine_rule,
            QueryRule(D, [C]),
        ]
    )


def test_transitive_params(transitive_params_rule_runner: RuleRunner) -> None:
    # Test that C can be provided and implicitly converted into a B with transitive_b_c() to satisfy
    # the selectors of consumes_a_and_b().
    a, c = A(), C()
    result_str = transitive_params_rule_runner.request(str, [a, c])
    assert remove_locations_from_traceback(result_str) == remove_locations_from_traceback(
        consumes_a_and_b(a, transitive_b_c(c))
    )

    # Test that an inner Get in transitive_coroutine_rule() is able to resolve B from C due to
    # the existence of transitive_b_c().
    transitive_params_rule_runner.request(D, [c])


def test_consumed_types(transitive_params_rule_runner: RuleRunner) -> None:
    assert {A, B, C, str} == set(
        transitive_params_rule_runner.scheduler.scheduler.rule_graph_consumed_types([A, C], str)
    )


@rule
def boolean_and_int(i: int, b: bool) -> A:
    return A()


def test_strict_equals() -> None:
    rule_runner = RuleRunner(rules=[boolean_and_int, QueryRule(A, [int, bool])])
    # With the default implementation of `__eq__` for boolean and int, `1 == True`. But in the
    # engine, that behavior would be surprising and would cause both of these Params to intern
    # to the same value, triggering an error. Instead, the engine additionally includes the
    # type of a value in equality.
    assert A() == rule_runner.request(A, [1, True])


# -----------------------------------------------------------------------------------------------
# Test unions
# -----------------------------------------------------------------------------------------------


@union
class Vehicle(ABC):
    @abstractmethod
    def num_wheels(self) -> int:
        pass


class Car(Vehicle):
    def num_wheels(self) -> int:
        return 4


class Motorcycle(Vehicle):
    def num_wheels(self) -> int:
        return 2


@rule
def car_num_wheels(car: Car) -> int:
    return car.num_wheels()


@rule
def motorcycle_num_wheels(motorcycle: Motorcycle) -> int:
    return motorcycle.num_wheels()


@dataclass(frozen=True)
class WrappedVehicle:
    vehicle: Vehicle


@rule
async def generic_num_wheels(wrapped_vehicle: WrappedVehicle) -> int:
    return await Get(int, Vehicle, wrapped_vehicle.vehicle)


def test_union_rules() -> None:
    rule_runner = RuleRunner(
        rules=[
            car_num_wheels,
            motorcycle_num_wheels,
            UnionRule(Vehicle, Car),
            UnionRule(Vehicle, Motorcycle),
            generic_num_wheels,
            QueryRule(int, [WrappedVehicle]),
        ],
    )
    assert rule_runner.request(int, [WrappedVehicle(Car())]) == 4
    assert rule_runner.request(int, [WrappedVehicle(Motorcycle())]) == 2

    # Fails due to no union relationship between Vehicle -> str.
    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(int, [WrappedVehicle("not a vehicle")])  # type: ignore[arg-type]
    assert (
        "Invalid Get. Because the second argument to `Get(int, Vehicle, not a vehicle)` is "
        "annotated with `@union`, the third argument should be a member of that union. Did you "
        "intend to register `UnionRule(Vehicle, str)`?"
    ) in str(exc.value.args[0])



class SomeInput:
    s: str


@dataclass(frozen=True)
class SomeOutput:
    s: str


@rule
def raise_an_exception(some_input: SomeInput) -> SomeOutput:
    raise Exception(some_input.s)


@dataclass(frozen=True)
class OuterInput:
    s: str


@rule
async def catch_an_exception(outer_input: OuterInput) -> SomeOutput:
    try:
        return await Get(SomeOutput, SomeInput(outer_input.s))
    except Exception as e:
        return SomeOutput(str(e))


@rule
async def catch_and_reraise(outer_input: OuterInput) -> SomeOutput:
    try:
        return await Get(SomeOutput, SomeInput(outer_input.s))
    except Exception:
        raise Exception("nested exception!")


class InputWithNothing:
    pass


GLOBAL_FLAG: bool = True


@rule
def raise_an_exception_upon_global_state(input_with_nothing: InputWithNothing) -> SomeOutput:
    if GLOBAL_FLAG:
        raise Exception("global flag is set!")
    return SomeOutput("asdf")


@rule
def return_a_wrong_product_type(input_with_nothing: InputWithNothing) -> A:
    return B()  # type: ignore[return-value]


@rule
async def catch_a_wrong_product_type(input_with_nothing: InputWithNothing) -> B:
    try:
        _ = await Get(A, InputWithNothing, input_with_nothing)
    except IncorrectProductError as e:
        raise Exception(f"caught product type error: {e}")
    return B()


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
            raise_an_exception,
            QueryRule(SomeOutput, (SomeInput,)),
            catch_an_exception,
            QueryRule(SomeOutput, (OuterInput,)),
            raise_an_exception_upon_global_state,
            QueryRule(SomeOutput, (InputWithNothing,)),
            return_a_wrong_product_type,
            QueryRule(A, (InputWithNothing,)),
            catch_a_wrong_product_type,
            QueryRule(B, (InputWithNothing,)),
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

    def test_catch_inner_exception(self):
        assert self.request(SomeOutput, [OuterInput("asdf")]) == SomeOutput("asdf")

    def test_exceptions_uncached(self):
        global GLOBAL_FLAG
        with self._assert_execution_error("global flag is set!"):
            self.request(SomeOutput, [InputWithNothing()])
        GLOBAL_FLAG = False
        assert self.request(SomeOutput, [InputWithNothing()]) == SomeOutput("asdf")

    def test_incorrect_product_type(self):
        with self._assert_execution_error("caught product type error"):
            self.request(B, [InputWithNothing()])


# -----------------------------------------------------------------------------------------------
# Test tracebacks
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
             raise Exception("An exception!")
         Exception: An exception!
         """
    )


# -----------------------------------------------------------------------------------------------
# Test unhashable types
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
            raise_an_exception,
            QueryRule(SomeOutput, (SomeInput,)),
            catch_and_reraise,
            QueryRule(SomeOutput, (OuterInput,)),
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

    def test_trace_includes_nested_exception_traceback(self):
        request = self.scheduler.execution_request([SomeOutput], [OuterInput("asdf")])
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
                   in {self.__module__}.{catch_and_reraise.__name__}
                   in {self.__module__}.{raise_an_exception.__name__}
                 Traceback (most recent call last):
                   File LOCATION-INFO, in raise_an_exception
                     raise Exception(some_input.s)
                 Exception: asdf

                 While handling that, another exception was raised:

                 Traceback (most recent call last):
                   File LOCATION-INFO, in catch_and_reraise
                     return await Get(SomeOutput, SomeInput(outer_input.s))
                   File LOCATION-INFO, in __await__
                     result = yield self
                 Exception: asdf

                 During handling of the above exception, another exception occurred:

                 Traceback (most recent call last):
                   File LOCATION-INFO, in generator_send
                     res = self._send_to_coroutine(func, arg)
                   File LOCATION-INFO, in _send_to_coroutine
                     return func.throw(arg)  # type: ignore[arg-type]
                   File LOCATION-INFO, in catch_and_reraise
                     raise Exception("nested exception!")
                 Exception: nested exception!
                 """
            ),
            trace,
        )
