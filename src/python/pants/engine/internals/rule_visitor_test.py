# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable, Tuple

import pytest

from pants.engine.internals.rule_visitor import collect_awaitables
from pants.engine.internals.selectors import Get, GetParseError, MultiGet
from pants.engine.rules import rule_helper

# The visitor inspects the module for definitions, so these must be at module scope
STR = str
INT = int
BOOL = bool


@rule_helper
async def _top_helper(arg1):
    a = await Get(STR, INT, arg1)
    return await _helper_helper(a)


@rule_helper
async def _helper_helper(arg1):
    return await Get(INT, STR, arg1)


class HelperContainer:
    @rule_helper
    async def _method_helper(self):
        return await Get(STR, INT, 42)

    @staticmethod
    @rule_helper
    async def _static_helper():
        a = await Get(STR, INT, 42)
        return await _helper_helper(a)


container_instance = HelperContainer()


def assert_awaitables(func, awaitable_types: Iterable[Tuple[type, type]]):
    gets = collect_awaitables(func)
    if any(len(get.input_types) != 1 for get in gets):
        raise AssertionError("TODO: Add support for multiple-parameter Gets.")
    get_types = tuple((get.input_types[0], get.output_type) for get in gets)
    assert get_types == tuple(awaitable_types)


def test_single_get() -> None:
    async def rule():
        await Get(STR, INT, 42)

    assert_awaitables(rule, [(int, str)])


def test_multiple_gets() -> None:
    async def rule():
        a = await Get(STR, INT, 42)
        if len(a) > 1:
            await Get(BOOL, STR("bob"))

    assert_awaitables(rule, [(int, str), (str, bool)])


def test_multiget_homogeneous() -> None:
    async def rule():
        await MultiGet(Get(STR, INT(x)) for x in range(5))

    assert_awaitables(rule, [(int, str)])


def test_multiget_heterogeneous() -> None:
    async def rule():
        await MultiGet(Get(STR, INT, 42), Get(INT, STR("bob")))

    assert_awaitables(rule, [(int, str), (str, int)])


def test_get_no_index_call_no_subject_call_allowed() -> None:
    async def rule():
        get_type: type = Get  # noqa: F841

    assert_awaitables(rule, [])


def test_rule_helpers_free_functions() -> None:
    async def rule():
        _top_helper(1)

    assert_awaitables(rule, [(int, str), (str, int)])


def test_rule_helpers_class_methods() -> None:
    async def rule1():
        HelperContainer()._static_helper(1)

    # Rule helpers must be called via module-scoped attributes
    assert_awaitables(rule1, [])

    async def rule2():
        container_instance._static_helper(1)

    assert_awaitables(rule2, [(int, str), (str, int)])

    async def rule3():
        container_instance._method_helper(1)

    assert_awaitables(rule3, [(int, str)])


def test_valid_get_unresolvable_product_type() -> None:
    async def rule():
        Get(DNE, STR(42))  # noqa: F821

    with pytest.raises(ValueError):
        collect_awaitables(rule)


def test_valid_get_unresolvable_subject_declared_type() -> None:
    async def rule():
        Get(int, DNE, "bob")  # noqa: F821

    with pytest.raises(ValueError):
        collect_awaitables(rule)


def test_invalid_get_no_subject_args() -> None:
    async def rule():
        Get(
            STR,
        )

    with pytest.raises(GetParseError):
        collect_awaitables(rule)


def test_invalid_get_too_many_subject_args() -> None:
    async def rule():
        Get(STR, INT, "bob", 3)

    with pytest.raises(GetParseError):
        collect_awaitables(rule)


def test_invalid_get_invalid_subject_arg_no_constructor_call() -> None:
    async def rule():
        Get(STR, "bob")

    with pytest.raises(GetParseError):
        collect_awaitables(rule)


def test_invalid_get_invalid_product_type_not_a_type_name() -> None:
    async def rule():
        Get(call(), STR("bob"))  # noqa: F821

    with pytest.raises(GetParseError):
        collect_awaitables(rule)
