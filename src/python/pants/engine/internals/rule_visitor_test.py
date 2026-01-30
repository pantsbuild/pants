# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib
import sys
import textwrap
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from pants.base.exceptions import RuleTypeError
from pants.engine.internals.rule_visitor import collect_awaitables
from pants.engine.internals.selectors import Get, GetParseError, concurrently
from pants.engine.rules import implicitly, rule
from pants.util.strutil import softwrap

# The visitor inspects the module for definitions.
STR = str
INT = int
BOOL = bool


@rule
async def str_from_int(i: int) -> str:
    return str(i)


@rule
async def int_from_str(s: str) -> int:
    return int(s)


async def _top_helper(arg1):
    a = await str_from_int(arg1)
    return await _helper_helper(a)


async def _helper_helper(arg1):
    return await int_from_str(arg1)


class HelperContainer:
    async def _method_helper(self, arg1: int):
        return await str_from_int(**implicitly({arg1: int}))

    @staticmethod
    async def _static_helper():
        a = await str_from_int(42)
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


def assert_byname_awaitables(func, awaitable_types: Iterable[tuple[OutT, InT | list[InT], int]]):
    gets = collect_awaitables(func)
    actual_types = tuple(
        (get.output_type, list(get.input_types), get.explicit_args_arity) for get in gets
    )
    expected_types = tuple(
        (output, ([input_] if isinstance(input_, type) else input_), explicit_args_arity)
        for output, input_, explicit_args_arity in awaitable_types
    )
    assert actual_types == expected_types


@pytest.mark.call_by_type
def test_single_get() -> None:
    async def rule():
        await Get(STR, INT, 42)

    assert_awaitables(rule, [(str, int)])


@pytest.mark.call_by_type
def test_single_no_args_syntax() -> None:
    async def rule():
        await Get(STR)

    assert_awaitables(rule, [(str, [])])


@pytest.mark.call_by_type
def test_get_multi_param_syntax() -> None:
    async def rule():
        await Get(str, {42: int, "towel": str})

    assert_awaitables(rule, [(str, [int, str])])


@pytest.mark.call_by_type
def test_multiple_gets() -> None:
    async def rule():
        a = await Get(STR, INT, 42)
        if len(a) > 1:
            await Get(BOOL, STR("bob"))

    assert_awaitables(rule, [(str, int), (bool, str)])


@pytest.mark.call_by_type
def test_multiget_homogeneous() -> None:
    async def rule():
        await concurrently(Get(STR, INT(x)) for x in range(5))

    assert_awaitables(rule, [(str, int)])


@pytest.mark.call_by_type
def test_multiget_heterogeneous() -> None:
    async def rule():
        await concurrently(Get(STR, INT, 42), Get(INT, STR("bob")))

    assert_awaitables(rule, [(str, int), (int, str)])


@pytest.mark.call_by_type
def test_attribute_lookup() -> None:
    async def rule1():
        await Get(InnerScope.STR, InnerScope.INT, 42)
        await Get(InnerScope.STR, InnerScope.INT(42))

    assert_awaitables(rule1, [(str, int), (str, int)])


@pytest.mark.call_by_type
def test_get_no_index_call_no_subject_call_allowed() -> None:
    async def rule() -> None:
        get_type: type = Get  # noqa: F841

    assert_awaitables(rule, [])


def test_byname() -> None:
    @rule
    async def rule0() -> int:
        return 11

    @rule
    async def rule1(arg: int) -> int:
        return arg

    @rule
    async def rule2(arg1: float, arg2: str) -> int:
        return int(arg1) + int(arg2)

    async def rule3() -> int:
        r0 = await rule0()
        r1_explicit = await rule1(22)
        r1_implicit = await rule1(**implicitly(int(23)))
        r2_explicit = await rule2(33.3, "44")
        r2_implicit = await rule2(**implicitly({33.4: float, "45": str}))
        r2_mixed = await rule2(33.5, **implicitly({"45": str}))
        return r0 + r1_explicit + r1_implicit + r2_explicit + r2_implicit + r2_mixed

    assert_byname_awaitables(
        rule3,
        [
            (int, [], 0),
            (int, [], 1),
            (int, int, 0),
            (int, [], 2),
            (int, [float, str], 0),
            (int, [str], 1),
        ],
    )


@contextmanager
def temporary_module(tmp_path: Path, rule_code: str):
    module_name = "_temp_module"
    src_file = tmp_path / f"{module_name}.py"
    with open(src_file, "w") as fp:
        fp.write(rule_code)
    spec = importlib.util.spec_from_file_location(module_name, src_file)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    assert module
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules[module_name]


def test_byname_recursion(tmp_path: Path) -> None:
    # Note that it's important that the rule is defined inside this function, so that
    # the @rule decorator is evaluated at test runtime, and not test file parse time.
    # However recursion is only supported for rules at module scope, so we have to
    # jump through some hoops to create a module at runtime.

    rule_code = textwrap.dedent("""
        from pants.engine.rules import rule

        @rule
        async def recursive_rule(arg: int) -> int:
            if arg == 0:
                return 0
            recursive = await recursive_rule(arg - 1)
            return recursive
    """)
    with temporary_module(tmp_path, rule_code) as module:
        assert_byname_awaitables(module.recursive_rule, [(int, [], 1)])


def test_byname_mutual_recursion(tmp_path: Path) -> None:
    # Note that it's important that the rules are defined inside this function, so that
    # the @rule decorators are evaluated at test runtime, and not test file parse time.
    # However recursion is only supported for rules at module scope, so we have to
    # jump through some hoops to create a module at runtime.

    rule_code = textwrap.dedent("""
        from pants.engine.rules import rule

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
    """)

    with temporary_module(tmp_path, rule_code) as module:
        assert_byname_awaitables(module.mutually_recursive_rule_1, [(str, [], 1)])
        assert_byname_awaitables(module.mutually_recursive_rule_2, [(int, [], 1)])


def test_rule_helpers_free_functions() -> None:
    async def rule():
        _top_helper(1)

    assert_byname_awaitables(rule, [(str, [], 1), (int, [], 1)])


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
    assert_byname_awaitables(rule1, [])
    assert_byname_awaitables(rule1_inner, [])
    assert_byname_awaitables(rule2, [(str, [], 1), (int, [], 1)])
    assert_byname_awaitables(rule2_inner, [(str, [], 1), (int, [], 1)])
    assert_byname_awaitables(rule3, [(str, [], 1), (int, [], 1)])
    assert_byname_awaitables(rule3_inner, [(str, [], 1), (int, [], 1)])
    assert_byname_awaitables(rule4, [(str, [int], 0)])
    assert_byname_awaitables(rule4_inner, [(str, int, 0)])


@pytest.mark.call_by_type
def test_valid_get_unresolvable_product_type() -> None:
    async def rule():
        Get(DNE, STR(42))  # noqa: F821

    with pytest.raises(RuleTypeError, match="Could not resolve type for `DNE` in module"):
        collect_awaitables(rule)


@pytest.mark.call_by_type
def test_valid_get_unresolvable_subject_declared_type() -> None:
    async def rule():
        Get(int, DNE, "bob")  # noqa: F821

    with pytest.raises(RuleTypeError, match="Could not resolve type for `DNE` in module"):
        collect_awaitables(rule)


@pytest.mark.call_by_type
def test_invalid_get_no_args() -> None:
    async def rule():
        Get()

    with pytest.raises(GetParseError):
        collect_awaitables(rule)


@pytest.mark.call_by_type
def test_invalid_get_too_many_subject_args() -> None:
    async def rule():
        Get(STR, INT, "bob", 3)

    with pytest.raises(GetParseError):
        collect_awaitables(rule)


@pytest.mark.call_by_type
def test_invalid_get_invalid_subject_arg_no_constructor_call() -> None:
    async def rule():
        Get(STR, "bob")

    with pytest.raises(RuleTypeError, match="Expected a type, but got: (Str|Constant) 'bob'"):
        collect_awaitables(rule)


@pytest.mark.call_by_type
def test_invalid_get_invalid_product_type_not_a_type_name() -> None:
    async def rule():
        Get(call(), STR("bob"))  # noqa: F821

    with pytest.raises(RuleTypeError, match="Expected a type, but got: Call 'call'"):
        collect_awaitables(rule)


@pytest.mark.call_by_type
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


@pytest.mark.call_by_type
def test_deep_infer_types() -> None:
    async def rule(request: Request):
        # 1
        r = await request._helped()
        Get(int, r.arg1)
        # 2
        s = request.arg2
        Get(bool, s)
        # 3, 4
        a, b = await concurrently(
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
        await concurrently([c, Get(str, dict)])
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


@pytest.mark.call_by_type
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


@pytest.mark.call_by_type
def test_closure() -> None:
    def closure_func() -> int:
        return 44

    async def myrule(request: Request):
        Get(str, closure_func())

    assert_awaitables(myrule, [(str, int)])


class McUnion:
    b: bool
    v: int | float


@pytest.mark.call_by_type
def test_union_types() -> None:
    async def somerule(mc: McUnion):
        Get(str, mc.b)

    assert_awaitables(somerule, [(str, bool)])
