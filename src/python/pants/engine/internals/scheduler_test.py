# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from textwrap import dedent
from typing import Any

import pytest

from pants.base.exceptions import IncorrectProductError
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import Get, MultiGet, implicitly, rule
from pants.engine.unions import UnionRule, union
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error

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
    rule_runner = RuleRunner(
        rules=[consumes_a_and_b, QueryRule(str, [A, B])],
        inherent_environment=None,
    )

    # Confirm that we can pass in Params in order to provide multiple inputs to an execution.
    a, b = A(), B()
    result_str = rule_runner.request(str, [a, b])
    assert result_str == consumes_a_and_b.rule.func(a, b)  # type: ignore[attr-defined]

    # And confirm that a superset of Params is also accepted.
    result_str = rule_runner.request(str, [a, b, b"bytes aren't used by any rules"])
    assert result_str == consumes_a_and_b.rule.func(a, b)  # type: ignore[attr-defined]

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
        ],
        inherent_environment=None,
    )


def test_transitive_params(transitive_params_rule_runner: RuleRunner) -> None:
    # Test that C can be provided and implicitly converted into a B with transitive_b_c() to satisfy
    # the selectors of consumes_a_and_b().
    a, c = A(), C()
    assert transitive_params_rule_runner.request(str, [a, c])

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
# Test direct @rule calls
# -----------------------------------------------------------------------------------------------


@rule
async def b(i: int) -> B:
    return B()


@rule
def c() -> C:
    return C()


@rule
async def a() -> A:
    _ = await b(**implicitly(int(1)))
    _ = await c()
    b1, c1, b2 = await MultiGet(
        b(1),
        c(),
        Get(B, int(1)),
    )
    return A()


def test_direct_call() -> None:
    rule_runner = RuleRunner(
        rules=[
            a,
            b,
            c,
            QueryRule(A, []),
        ]
    )
    assert rule_runner.request(A, [])


# -----------------------------------------------------------------------------------------------
# Test unions
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fuel:
    pass


@union(in_scope_types=[Fuel])
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
def car_num_wheels(car: Car, _: Fuel) -> int:
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


def test_union_rules_in_scope_via_query() -> None:
    rule_runner = RuleRunner(
        rules=[
            car_num_wheels,
            motorcycle_num_wheels,
            UnionRule(Vehicle, Car),
            UnionRule(Vehicle, Motorcycle),
            generic_num_wheels,
            QueryRule(int, [WrappedVehicle, Fuel]),
        ],
    )
    assert rule_runner.request(int, [WrappedVehicle(Car()), Fuel()]) == 4
    assert rule_runner.request(int, [WrappedVehicle(Motorcycle()), Fuel()]) == 2

    # Fails due to no union relationship between Vehicle -> str.
    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(int, [WrappedVehicle("not a vehicle"), Fuel()])  # type: ignore[arg-type]
    assert (
        "Invalid Get. Because an input type for `Get(int, Vehicle, not a vehicle)` was "
        "annotated with `@union`, the value for that type should be a member of that union. Did you "
        "intend to register a `UnionRule`?"
    ) in str(exc.value.args[0])


def test_union_rules_in_scope_computed() -> None:
    @rule
    def fuel_singleton() -> Fuel:
        return Fuel()

    rule_runner = RuleRunner(
        rules=[
            car_num_wheels,
            motorcycle_num_wheels,
            UnionRule(Vehicle, Car),
            UnionRule(Vehicle, Motorcycle),
            generic_num_wheels,
            fuel_singleton,
            QueryRule(int, [WrappedVehicle]),
        ],
    )
    assert rule_runner.request(int, [WrappedVehicle(Car())]) == 4
    assert rule_runner.request(int, [WrappedVehicle(Motorcycle())]) == 2


# -----------------------------------------------------------------------------------------------
# Test invalid Gets
# -----------------------------------------------------------------------------------------------


def create_outlined_get() -> Get[int]:
    return Get(int, str, "hello")


@rule
async def uses_outlined_get() -> int:
    return await create_outlined_get()


def test_outlined_get() -> None:
    rule_runner = RuleRunner(
        rules=[
            uses_outlined_get,
            QueryRule(int, []),
        ],
    )
    # Fails because the creation of the `Get` was out-of-lined into a separate function.
    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(int, [])
    assert (
        "Get(int, str, hello) was not detected in your @rule body at rule compile time."
    ) in str(exc.value.args[0])


@rule
async def uses_rule_helper_before_definition() -> int:
    return await get_after_rule()


async def get_after_rule() -> int:
    return await Get(int, str, "hello")


def test_rule_helper_after_rule_definition_fails() -> None:
    rule_runner = RuleRunner(
        rules=[
            uses_rule_helper_before_definition,
            QueryRule(int, []),
        ],
    )

    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(int, [])
    assert (
        "Get(int, str, hello) was not detected in your @rule body at rule compile time."
    ) in str(exc.value.args[0])


@dataclass(frozen=True)
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


@rule(desc="error chain")
async def catch_and_reraise(outer_input: OuterInput) -> SomeOutput:
    """This rule is used in a dedicated test only, so does not conflict with
    `catch_an_exception`."""
    try:
        return await Get(SomeOutput, SomeInput(outer_input.s))
    except Exception as e:
        raise Exception("nested exception!") from e


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


@pytest.fixture
def rule_error_runner() -> RuleRunner:
    return RuleRunner(
        rules=(
            consumes_a_and_b,
            QueryRule(str, (A, B)),
            transitive_b_c,
            QueryRule(str, (A, C)),
            transitive_coroutine_rule,
            QueryRule(D, (C,)),
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
    )


def test_catch_inner_exception(rule_error_runner: RuleRunner) -> None:
    assert rule_error_runner.request(SomeOutput, [OuterInput("asdf")]) == SomeOutput("asdf")


def test_exceptions_uncached(rule_error_runner: RuleRunner) -> None:
    global GLOBAL_FLAG
    with engine_error(Exception, contains="global flag is set!"):
        rule_error_runner.request(SomeOutput, [InputWithNothing()])
    GLOBAL_FLAG = False
    assert rule_error_runner.request(SomeOutput, [InputWithNothing()]) == SomeOutput("asdf")


def test_incorrect_product_type(rule_error_runner: RuleRunner) -> None:
    with engine_error(Exception, contains="caught product type error"):
        rule_error_runner.request(B, [InputWithNothing()])


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
    normalized_traceback = dedent(
        f"""\
         1 Exception encountered:

         Engine traceback:
           in root
             ..
           in {__name__}.{nested_raise.__name__}
             Nested raise

         Traceback (most recent call last):
           File LOCATION-INFO, in nested_raise
             fn_raises()
           File LOCATION-INFO, in fn_raises
             raise Exception("An exception!")
         Exception: An exception!

         """
    )

    rule_runner = RuleRunner(rules=[nested_raise, QueryRule(A, [])])
    with engine_error(Exception, contains=normalized_traceback, normalize_tracebacks=True):
        rule_runner.request(A, [])


def test_trace_includes_nested_exception_traceback() -> None:
    normalized_traceback = dedent(
        f"""\
        1 Exception encountered:

        Engine traceback:
          in root
            ..
          in {__name__}.{catch_and_reraise.__name__}
            error chain
          in {__name__}.{raise_an_exception.__name__}
            ..

        Traceback (most recent call last):
          File LOCATION-INFO, in raise_an_exception
            raise Exception(some_input.s)
        Exception: asdf

        During handling of the above exception, another exception occurred:

        Traceback (most recent call last):
          File LOCATION-INFO, in catch_and_reraise
            return await Get(SomeOutput, SomeInput(outer_input.s))
          File LOCATION-INFO, in __await__
            result = yield self
        Exception: asdf

        The above exception was the direct cause of the following exception:

        Traceback (most recent call last):
          File LOCATION-INFO, in catch_and_reraise
            raise Exception("nested exception!") from e
        Exception: nested exception!
        """
    )

    rule_runner = RuleRunner(
        rules=[
            raise_an_exception,
            catch_and_reraise,
            QueryRule(SomeOutput, (OuterInput,)),
        ]
    )
    with engine_error(Exception, contains=normalized_traceback, normalize_tracebacks=True):
        rule_runner.request(SomeOutput, [OuterInput("asdf")])


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
