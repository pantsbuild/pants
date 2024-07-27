# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pytest

from pants.base.exceptions import RuleTypeError
from pants.engine.internals.rule_visitor import collect_awaitables
from pants.engine.internals.selectors import Get, GetParseError, MultiGet
from pants.engine.rules import implicitly, rule
from pants.util.strutil import softwrap

# The visitor inspects the module for definitions.
STR = str
INT = int
BOOL = bool


async def _top_helper(arg1):
    a = await Get(STR, INT, arg1)
    return await _helper_helper(a)


async def _helper_helper(arg1):
    return await Get(INT, STR, arg1)


class HelperContainer:
    async def _method_helper(self):
        return await Get(STR, INT, 42)

    @staticmethod
    async def _static_helper():
        a = await Get(STR, INT, 42)
        return await _helper_helper(a)


container_instance = HelperContainer()


class InnerScope:
    STR = str
    INT = int
    BOOL = bool

    HelperContainer = HelperContainer
    container_instance = container_instance


OutT = type
InT = type


def assert_awaitables(func, awaitable_types: Iterable[tuple[OutT, InT | list[InT]]]):
    gets = collect_awaitables(func)
    actual_types = tuple((get.output_type, list(get.input_types)) for get in gets)
    expected_types = tuple(
        (output, ([input_] if isinstance(input_, type) else input_))
        for output, input_ in awaitable_types
    )
    assert actual_types == expected_types


def test_single_get() -> None:
    async def rule():
        await Get(STR, INT, 42)

    assert_awaitables(rule, [(str, int)])


def test_single_no_args_syntax() -> None:
    async def rule():
        await Get(STR)

    assert_awaitables(rule, [(str, [])])


def test_get_multi_param_syntax() -> None:
    async def rule():
        await Get(str, {42: int, "towel": str})

    assert_awaitables(rule, [(str, [int, str])])


def test_multiple_gets() -> None:
    async def rule():
        a = await Get(STR, INT, 42)
        if len(a) > 1:
            await Get(BOOL, STR("bob"))

    assert_awaitables(rule, [(str, int), (bool, str)])


def test_multiget_homogeneous() -> None:
    async def rule():
        await MultiGet(Get(STR, INT(x)) for x in range(5))

    assert_awaitables(rule, [(str, int)])


def test_multiget_heterogeneous() -> None:
    async def rule():
        await MultiGet(Get(STR, INT, 42), Get(INT, STR("bob")))

    assert_awaitables(rule, [(str, int), (int, str)])


def test_attribute_lookup() -> None:
    async def rule1():
        await Get(InnerScope.STR, InnerScope.INT, 42)
        await Get(InnerScope.STR, InnerScope.INT(42))

    assert_awaitables(rule1, [(str, int), (str, int)])


def test_get_no_index_call_no_subject_call_allowed() -> None:
    async def rule() -> None:
        get_type: type = Get  # noqa: F841

    assert_awaitables(rule, [])


def test_byname() -> None:
    @rule
    def rule1(arg: int) -> int:
        return arg

    @rule
    async def rule2() -> int:
        return 2

    async def rule3() -> int:
        one_explicit = await rule1(1)
        one_implicit = await rule1(**implicitly(int(1)))
        two = await rule2()
        return one_explicit + one_implicit + two

    assert_awaitables(rule3, [(int, []), (int, int), (int, [])])


def test_byname_recursion() -> None:
    # Note that it's important that the rule is defined inside this function, so that
    # the @rule decorator is evaluated at test runtime, and not test file parse time.
    @rule
    async def recursive_rule(arg: int) -> int:
        if arg == 0:
            return 0
        recursive = await recursive_rule(arg - 1)
        return recursive

    assert_awaitables(recursive_rule, [(int, [])])


@pytest.mark.xfail(
    reason="We don't yet support mutual recursion via call-by-name.",
    run=False,
)
def test_byname_mutual_recursion() -> None:
    @rule
    async def mutually_recursive_rule_1(arg: str) -> int:
        if arg == "0":
            return 0
        recursive = await mutually_recursive_rule_2(int(arg) - 1)
        return int(recursive)

    @rule
    async def mutually_recursive_rule_2(arg: int) -> str:
        recursive = await mutually_recursive_rule_1(str(arg - 1))
        return str(recursive)

    assert_awaitables(mutually_recursive_rule_1, [(str, [])])
    assert_awaitables(mutually_recursive_rule_2, [(int, [])])


def test_rule_helpers_free_functions() -> None:
    async def rule():
        _top_helper(1)

    assert_awaitables(rule, [(str, int), (int, str)])


def test_rule_helpers_class_methods() -> None:
    async def rule1():
        HelperContainer()._static_helper(1)

    async def rule1_inner():
        InnerScope.HelperContainer()._static_helper(1)

    async def rule2():
        HelperContainer._static_helper(1)

    async def rule2_inner():
        InnerScope.HelperContainer._static_helper(1)

    async def rule3():
        container_instance._static_helper(1)

    async def rule3_inner():
        InnerScope.container_instance._static_helper(1)

    async def rule4():
        container_instance._method_helper(1)

    async def rule4_inner():
        InnerScope.container_instance._method_helper(1)

    # Rule helpers must be called via module-scoped attribute lookup
    assert_awaitables(rule1, [])
    assert_awaitables(rule1_inner, [])
    assert_awaitables(rule2, [(str, int), (int, str)])
    assert_awaitables(rule2_inner, [(str, int), (int, str)])
    assert_awaitables(rule3, [(str, int), (int, str)])
    assert_awaitables(rule3_inner, [(str, int), (int, str)])
    assert_awaitables(rule4, [(str, int)])
    assert_awaitables(rule4_inner, [(str, int)])


def test_valid_get_unresolvable_product_type() -> None:
    async def rule():
        Get(DNE, STR(42))  # noqa: F821

    with pytest.raises(RuleTypeError, match="Could not resolve type for `DNE` in module"):
        collect_awaitables(rule)


def test_valid_get_unresolvable_subject_declared_type() -> None:
    async def rule():
        Get(int, DNE, "bob")  # noqa: F821

    with pytest.raises(RuleTypeError, match="Could not resolve type for `DNE` in module"):
        collect_awaitables(rule)


def test_invalid_get_no_args() -> None:
    async def rule():
        Get()

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

    with pytest.raises(RuleTypeError, match="Expected a type, but got: (Str|Constant) 'bob'"):
        collect_awaitables(rule)


def test_invalid_get_invalid_product_type_not_a_type_name() -> None:
    async def rule():
        Get(call(), STR("bob"))  # noqa: F821

    with pytest.raises(RuleTypeError, match="Expected a type, but got: Call 'call'"):
        collect_awaitables(rule)


def test_invalid_get_dict_value_not_type() -> None:
    async def rule():
        Get(int, {"str": "not a type"})

    with pytest.raises(
        RuleTypeError, match="Expected a type, but got: (Str|Constant) 'not a type'"
    ):
        collect_awaitables(rule)


@dataclass(frozen=True)
class Request:
    arg1: str
    arg2: float

    async def _helped(self) -> Request:
        return self

    @staticmethod
    def create_get() -> Get:
        return Get(Request, int)

    def bad_meth(self):
        return Request("uh", 4.2)


def test_deep_infer_types() -> None:
    async def rule(request: Request):
        # 1
        r = await request._helped()
        Get(int, r.arg1)
        # 2
        s = request.arg2
        Get(bool, s)
        # 3, 4
        a, b = await MultiGet(
            Get(list, str),
            Get(tuple, str),
        )
        # 5
        Get(dict, a)
        # 6
        Get(dict, b)
        # 7 -- this is huge!
        c = Request.create_get()
        # 8 -- the `c` is already accounted for, make sure it's not duplicated.
        await MultiGet([c, Get(str, dict)])
        # 9
        Get(float, request._helped())

    assert_awaitables(
        rule,
        [
            (int, str),  # 1
            (bool, float),  # 2
            (list, str),  # 3
            (tuple, str),  # 4
            (dict, list),  # 5
            (dict, tuple),  # 6
            (Request, int),  # 7
            (str, dict),  # 8
            (float, Request),  # 9
        ],
    )


def test_missing_type_annotation() -> None:
    async def myrule(request: Request):
        Get(str, request.bad_meth())

    err = softwrap(
        r"""
        /.*/rule_visitor_test\.py:\d+: Could not resolve type for `request\.bad_meth`
        in module pants\.engine\.internals\.rule_visitor_test\.

        Failed to look up return type hint for `bad_meth` in /.*/rule_visitor_test\.py:\d+
        """
    )
    with pytest.raises(RuleTypeError, match=err):
        collect_awaitables(myrule)


def test_closure() -> None:
    def closure_func() -> int:
        return 44

    async def myrule(request: Request):
        Get(str, closure_func())

    assert_awaitables(myrule, [(str, int)])


class McUnion:
    b: bool
    v: int | float


def test_union_types() -> None:
    async def somerule(mc: McUnion):
        Get(str, mc.b)

    assert_awaitables(somerule, [(str, bool)])
