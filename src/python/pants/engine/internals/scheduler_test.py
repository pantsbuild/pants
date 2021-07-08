# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from textwrap import dedent
from typing import Any

import pytest

from pants.engine.internals.engine_testutil import remove_locations_from_traceback
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


def create_outlined_get() -> Get[int, str]:
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
        "Get(int, str, hello) was not detected in your @rule body at rule compile time. "
        "Was the `Get` constructor called in a separate function, or perhaps "
        "dynamically? If so, it must be inlined into the @rule body."
    ) in str(exc.value.args[0])


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
