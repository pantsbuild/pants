# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib
import sys
import textwrap
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

from pants.engine.internals.rule_visitor import collect_awaitables
from pants.engine.rules import implicitly, rule

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
