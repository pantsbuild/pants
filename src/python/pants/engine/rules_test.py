# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from textwrap import dedent
from typing import Any, get_type_hints

import pytest

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.engine_testutil import assert_equal_with_printing
from pants.engine.internals.native_engine import PyExecutor
from pants.engine.internals.scheduler import Scheduler
from pants.engine.rules import (
    DuplicateRuleError,
    MissingParameterTypeAnnotation,
    MissingReturnTypeAnnotation,
    QueryRule,
    RuleIndex,
    UnrecognizedRuleArgument,
    goal_rule,
    rule,
)
from pants.engine.unions import UnionMembership
from pants.option.bootstrap_options import DEFAULT_EXECUTION_OPTIONS, DEFAULT_LOCAL_STORE_OPTIONS
from pants.testutil.rule_runner import run_rule_with_mocks
from pants.util.enums import match
from pants.util.logging import LogLevel


def create_scheduler(rules, validate=True):
    """Create a Scheduler."""
    return Scheduler(
        ignore_patterns=[],
        use_gitignore=False,
        build_root=str(Path.cwd()),
        pants_workdir="./.pants.d/workdir",
        local_execution_root_dir=".",
        named_caches_dir="./.pants.d/named_caches",
        ca_certs_path=None,
        rules=rules,
        union_membership=UnionMembership.empty(),
        executor=PyExecutor(core_threads=2, max_threads=4),
        execution_options=DEFAULT_EXECUTION_OPTIONS,
        local_store_options=DEFAULT_LOCAL_STORE_OPTIONS,
        validate_reachability=validate,
    )


def fmt_rule(
    rule: Callable, *, gets: list[tuple[str, str]] | None = None, multiline: bool = False
) -> str:
    """Generate the str that the engine will use for the rule.

    This is useful when comparing strings against engine error messages. Emulates the implementation
    of the DisplayForGraph trait.
    """

    def fmt_rust_function(func: Callable) -> str:
        return f"{func.__module__}:{func.__code__.co_firstlineno}:{func.__name__}"

    line_sep = "\n" if multiline else " "
    optional_line_sep = "\n" if multiline else ""

    rule = rule.rule.func  # type: ignore[attr-defined]
    type_hints = get_type_hints(rule)
    product = type_hints.pop("return").__name__
    params = f",{line_sep}".join(t.__name__ for t in type_hints.values())
    params_str = (
        f"{optional_line_sep}{params}{optional_line_sep}" if len(type_hints) > 1 else params
    )
    gets_str = ""
    if gets:
        get_members = f",{line_sep}".join(
            f"Get({product_subject_pair[0]}, [{product_subject_pair[1]}])"
            for product_subject_pair in gets
        )
        gets_str = f", gets=[{optional_line_sep}{get_members}{optional_line_sep}]"
    return f"@rule({fmt_rust_function(rule)}({params_str}) -> {product}{gets_str})"


@dataclass(frozen=True)
class RuleFormatRequest:
    rule: Callable
    for_param: type | tuple[type, ...] | None = None
    gets: list[tuple[str, str]] | None = None

    def format(self) -> str:
        msg = fmt_rule(self.rule, gets=self.gets, multiline=True)
        if self.for_param is not None:
            if isinstance(self.for_param, type):
                msg += f"\nfor {self.for_param.__name__}"
            else:
                joined = ", ".join(c.__name__ for c in self.for_param)
                msg += f"\nfor ({joined})"
        return msg

    @classmethod
    def format_rule(cls, obj):
        assert obj is not None

        if isinstance(obj, cls):
            return obj.format()
        if isinstance(obj, type):
            return f"Query({obj.__name__})"
        return fmt_rule(obj, multiline=True)


def fmt_param_edge(
    param: type[Any],
    product: type[Any] | tuple[type[Any], ...],
    via_func: type[Any] | RuleFormatRequest,
    return_func: RuleFormatRequest | None = None,
) -> str:
    if isinstance(via_func, type):
        via_func_str = f"Select({via_func.__name__})"
    else:
        via_func_str = RuleFormatRequest.format_rule(via_func)

    if isinstance(product, type):
        product_name = product.__name__
    else:
        joined = ", ".join(p.__name__ for p in product)
        product_name = f"({joined})"

    return_elements = []
    if return_func is not None:
        return_func_str = return_func.format()
        return_elements.append(return_func_str)
    return_elements.append(f"Param({param.__name__})")
    return_str = " ".join(f'"{el}"' for el in return_elements)

    param_color_fmt_str = GraphVertexType.param.graph_vertex_color_fmt_str()
    return dedent(
        f"""\
        "Param({param.__name__})" {param_color_fmt_str}    "{via_func_str}
        for {product_name}" -> {{{return_str}}}\
        """
    )


class GraphVertexType(Enum):
    task = "task"
    inner = "inner"
    singleton = "singleton"
    intrinsic = "intrinsic"
    param = "param"

    def graph_vertex_color_fmt_str(self) -> str | None:
        olive = "0.2214,0.7179,0.8528"
        gray = "0.576,0,0.6242"
        orange = "0.08,0.5,0.976"
        blue = "0.5,1,0.9"

        color = match(
            self,
            {
                GraphVertexType.task: blue,
                GraphVertexType.inner: None,
                GraphVertexType.singleton: olive,
                GraphVertexType.intrinsic: gray,
                GraphVertexType.param: orange,
            },
        )
        if color is None:
            return None
        return f'[color="{color}",style=filled]'


def fmt_non_param_edge(
    subject: type | Callable | RuleFormatRequest,
    product: type | tuple[type, ...],
    return_func: RuleFormatRequest | None = None,
    rule_type: GraphVertexType = GraphVertexType.task,
    append_for_product: bool = True,
) -> str:
    if isinstance(product, type):
        product_name = product.__name__
    else:
        joined = ", ".join(p.__name__ for p in product)
        product_name = f"({joined})"

    if return_func is None:
        color = rule_type.graph_vertex_color_fmt_str()
        if color is None:
            via_return_func = "-> {}"
        else:
            via_return_func = color
    else:
        return_func_fmt = return_func.format()
        via_return_func = f'-> {{"{return_func_fmt}\nfor {product_name}"}}'

    via_func_subject = RuleFormatRequest.format_rule(subject)

    if rule_type == GraphVertexType.singleton:
        spacing = ""
    else:
        spacing = "    "

    if append_for_product:
        before_return = f"\nfor {product_name}"
    else:
        before_return = ""

    return dedent(
        f"""\
        {spacing}"{via_func_subject}{before_return}" {via_return_func}\
        """
    )


def remove_whitespace_from_graph_output(s: str) -> str:
    no_trailing_whitespace = re.sub(r"\s*\n\s*", "", s, flags=re.MULTILINE)
    no_pre_or_post_quotes_whitespace = re.sub(r'"\s+|\s+"', '"', no_trailing_whitespace)
    return no_pre_or_post_quotes_whitespace.strip()


def assert_equal_graph_output(expected, actual):
    return assert_equal_with_printing(
        expected, actual, uniform_formatter=remove_whitespace_from_graph_output
    )


class A:
    def __repr__(self) -> str:
        return "A()"


class B:
    def __repr__(self) -> str:
        return "B()"


class C:
    def __repr__(self) -> str:
        return "C()"


class D:
    def __repr__(self) -> str:
        return "D()"


def noop(*args):
    pass


class SubA(A):
    def __repr__(self) -> str:
        return "SubA()"


class ExampleSubsystem(GoalSubsystem):
    """An example."""

    name = "example"


class Example(Goal):
    subsystem_cls = ExampleSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@rule
async def str_to_a(s: str) -> A:
    raise NotImplementedError()


@goal_rule
async def a_goal_rule_generator(console: Console) -> Example:
    a = await str_to_a("a str!")
    console.print_stdout(str(a))
    return Example(exit_code=0)


class TestRule:
    def test_run_rule_goal_rule_generator(self) -> None:
        res = run_rule_with_mocks(
            a_goal_rule_generator,
            rule_args=[Console()],
            mock_calls={"pants.engine.rules_test.str_to_a": lambda _: A()},
        )
        assert res == Example(0)

    def test_side_effecting_inputs(self) -> None:
        @goal_rule
        async def valid_rule(console: Console, b: str) -> Example:
            return Example(exit_code=0)

        with pytest.raises(ValueError) as cm:

            @rule
            async def invalid_rule(console: Console, b: str) -> bool:
                return False

        error_str = str(cm.value)
        assert (
            "(@rule pants.engine.rules_test:invalid_rule) may not have a side-effecting parameter"
            in error_str
        )
        assert "pants.engine.console.Console" in error_str


def test_rule_index_creation_fails_with_bad_declaration_type():
    with pytest.raises(TypeError) as exc:
        RuleIndex.create([A()])
    assert str(exc.value) == (
        "Rule entry A() had an unexpected type: <class 'pants.engine.rules_test.A'>. Rules "
        "either extend Rule or UnionRule, or are static functions decorated with @rule."
    )


class TestRuleArgumentAnnotation:
    def test_annotations_kwargs(self) -> None:
        @rule(level=LogLevel.INFO)
        async def a_named_rule(a: int, b: str) -> bool:
            return False

        assert a_named_rule.rule is not None  # type: ignore[attr-defined]
        assert (
            a_named_rule.rule.canonical_name  # type: ignore[attr-defined]
            == "pants.engine.rules_test.TestRuleArgumentAnnotation.test_annotations_kwargs.a_named_rule"
        )
        assert a_named_rule.rule.desc is None  # type: ignore[attr-defined]
        assert a_named_rule.rule.level == LogLevel.INFO  # type: ignore[attr-defined]

        @rule(canonical_name="something_different", desc="Human readable desc")
        async def another_named_rule(a: int, b: str) -> bool:
            return False

        assert a_named_rule.rule is not None  # type: ignore[attr-defined]
        assert another_named_rule.rule.canonical_name == "something_different"  # type: ignore[attr-defined]
        assert another_named_rule.rule.desc == "Human readable desc"  # type: ignore[attr-defined]
        assert another_named_rule.rule.level == LogLevel.TRACE  # type: ignore[attr-defined]

    def test_bogus_rules(self) -> None:
        with pytest.raises(UnrecognizedRuleArgument):

            @rule(bogus_kwarg="TOTALLY BOGUS!!!!!!")  # type: ignore
            async def a_named_rule(a: int, b: str) -> bool:
                return False

    def test_goal_rule_automatically_gets_desc_from_goal(self):
        @goal_rule
        async def some_goal_rule() -> Example:
            return Example(exit_code=0)

        assert some_goal_rule.rule.desc == "`example` goal"

    def test_can_override_goal_rule_name(self) -> None:
        @goal_rule(canonical_name="some_other_name")
        async def some_goal_rule() -> Example:
            return Example(exit_code=0)

        name = some_goal_rule.rule.canonical_name  # type: ignore[attr-defined]
        assert name == "some_other_name"


class TestGraphVertexTypeAnnotation:
    def test_nominal(self):
        @rule
        async def dry(a: int, b: str, c: float) -> bool:
            return False

        assert dry.rule is not None

    def test_missing_return_annotation(self) -> None:
        with pytest.raises(MissingReturnTypeAnnotation):

            @rule
            async def dry(a: int, b: str, c: float):
                return False

    def test_bad_return_annotation(self):
        with pytest.raises(MissingReturnTypeAnnotation):

            @rule
            async def dry(a: int, b: str, c: float) -> 42:
                return False

    def test_missing_parameter_annotation(self) -> None:
        with pytest.raises(MissingParameterTypeAnnotation):

            @rule
            async def dry(a: int, b, c: float) -> bool:
                return False

    def test_bad_parameter_annotation(self):
        with pytest.raises(MissingParameterTypeAnnotation):

            @rule
            async def dry(a: int, b: 42, c: float) -> bool:
                return False


def test_goal_rule_not_properly_marked_goal_rule() -> None:
    with pytest.raises(TypeError) as exc:

        @rule
        async def normal_rule_trying_to_return_a_goal() -> Example:
            return Example(0)

    assert (
        str(exc.value)
        == "An `@rule` that returns a `Goal` must instead be declared with `@goal_rule`."
    )


def test_goal_rule_not_returning_a_goal() -> None:
    with pytest.raises(TypeError) as exc:

        @goal_rule
        async def goal_rule_returning_a_non_goal() -> int:
            return 0

    assert str(exc.value) == "An `@goal_rule` must return a subclass of `engine.goal.Goal`."


class TestRuleGraph:
    def test_ruleset_with_ambiguity(self) -> None:
        @rule
        async def a_from_b_and_c(b: B, c: C) -> A:
            return A()

        @rule
        async def a_from_c_and_b(c: C, b: B) -> A:
            return A()

        rules = [a_from_b_and_c, a_from_c_and_b, QueryRule(A, (B, C))]
        with pytest.raises(Exception) as cm:
            create_scheduler(rules)

        assert_equal_graph_output(
            dedent(
                f"""\
                Encountered 1 rule graph error:
                  Too many sources of dependency A for Query(A for (B, C)): [
                        "{fmt_rule(a_from_c_and_b)} (for (B, C))",
                        "{fmt_rule(a_from_b_and_c)} (for (B, C))",
                    ]
                """
            ),
            str(cm.value),
        )

    def test_ruleset_with_valid_root(self) -> None:
        @rule
        async def a_from_b(b: B) -> A:
            return A()

        rules = [a_from_b, QueryRule(A, (B,))]
        create_scheduler(rules)

    def test_ruleset_with_unreachable_root(self) -> None:
        @rule
        async def a_from_b(b: B) -> A:
            return A()

        rules = [a_from_b, QueryRule(A, ())]
        with pytest.raises(Exception) as cm:
            create_scheduler(rules)
        assert (
            "No installed rules return the type B, and it was not provided by potential callers of "
        ) in str(cm.value)
        assert (
            "If that type should be computed by a rule, ensure that that rule is installed."
        ) in str(cm.value)
        assert (
            "If it should be provided by a caller, ensure that it is included in any relevant "
            "Query or Get."
        ) in str(cm.value)

    def test_smallest_full_test(self) -> None:
        @rule
        async def a_from_suba(suba: SubA) -> A:
            return A()

        rules = [a_from_suba, QueryRule(A, (SubA,))]
        fullgraph = self.create_full_graph(rules)
        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  /*
                  queries:
                       Query(A for SubA)
                  */
                  // root entries
                {fmt_non_param_edge(A, SubA)}
                {fmt_non_param_edge(A, SubA, RuleFormatRequest(a_from_suba))}
                  // internal entries
                {fmt_param_edge(SubA, SubA, RuleFormatRequest(a_from_suba))}
                }}"""
            ).strip(),
            fullgraph,
        )

    def test_smallest_full_test_multiple_root_subject_types(self) -> None:
        @rule
        async def a_from_suba(suba: SubA) -> A:
            return A()

        @rule
        async def b_from_a(a: A) -> B:
            return B()

        rules = [a_from_suba, QueryRule(A, (SubA,)), b_from_a, QueryRule(B, (A,))]
        fullgraph = self.create_full_graph(rules)
        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  /*
                  queries:
                    Query(A for SubA),
                    Query(B for A)
                  */
                  // root entries
                {fmt_non_param_edge(A, SubA)}
                {fmt_non_param_edge(A, SubA, RuleFormatRequest(a_from_suba))}
                {fmt_non_param_edge(B, A)}
                {fmt_non_param_edge(B, A, RuleFormatRequest(b_from_a))}
                  // internal entries
                {fmt_param_edge(A, A, RuleFormatRequest(b_from_a))}
                {fmt_param_edge(SubA, SubA, RuleFormatRequest(a_from_suba))}
                }}"""
            ).strip(),
            fullgraph,
        )

    def test_single_rule_depending_on_subject_selection(self) -> None:
        @rule
        async def a_from_suba(suba: SubA) -> A:
            return A()

        rules = [a_from_suba, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA())
        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  /*
                  queries:
                    Query(A for SubA)
                  */
                  // root entries
                {fmt_non_param_edge(A, SubA)}
                {fmt_non_param_edge(A, SubA, RuleFormatRequest(a_from_suba))}
                  // internal entries
                {fmt_param_edge(SubA, SubA, RuleFormatRequest(a_from_suba))}
                }}"""
            ).strip(),
            subgraph,
        )

    def test_multiple_selects(self) -> None:
        @rule
        async def a_from_suba_and_b(suba: SubA, b: B) -> A:
            return A()

        @rule
        async def b() -> B:
            return B()

        rules = [a_from_suba_and_b, b, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA())
        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  /*
                  queries:
                    Query(A for SubA)
                  */
                  // root entries
                {fmt_non_param_edge(A, SubA)}
                {fmt_non_param_edge(A, SubA, RuleFormatRequest(a_from_suba_and_b))}
                  // internal entries
                {fmt_non_param_edge(b, (), rule_type=GraphVertexType.inner)}
                {fmt_non_param_edge(b, (), rule_type=GraphVertexType.singleton)}
                {fmt_param_edge(SubA, SubA, RuleFormatRequest(a_from_suba_and_b), RuleFormatRequest(b, ()))}
                }}"""
            ).strip(),
            subgraph,
        )

    def test_one_level_of_recursion(self) -> None:
        @rule
        async def a_from_b(b: B) -> A:
            return A()

        @rule
        async def b_from_suba(suba: SubA) -> B:
            return B()

        rules = [a_from_b, b_from_suba, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA())
        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  /*
                  queries:
                    Query(A for SubA)
                  */
                  // root entries
                {fmt_non_param_edge(A, SubA)}
                {fmt_non_param_edge(A, SubA, RuleFormatRequest(a_from_b))}
                  // internal entries
                {fmt_non_param_edge(a_from_b, SubA, RuleFormatRequest(b_from_suba))}
                {fmt_param_edge(SubA, SubA, via_func=RuleFormatRequest(b_from_suba))}
                }}"""
            ).strip(),
            subgraph,
        )

    @pytest.mark.skip(reason="TODO(#10649): figure out if this tests is still relevant.")
    @pytest.mark.no_error_if_skipped
    def test_noop_removal_in_subgraph(self) -> None:
        @rule
        async def a_from_c(c: C) -> A:
            return A()

        @rule
        async def a() -> A:
            return A()

        @rule
        async def b_singleton() -> B:
            return B()

        rules = [a_from_c, a, b_singleton, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA(), validate=False)
        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  /*
                  queries:
                    Query(A for SubA)
                  */
                  // root entries
                {fmt_non_param_edge(A, ())}
                {fmt_non_param_edge(a, (), rule_type=GraphVertexType.singleton)}
                {fmt_non_param_edge(A, (), RuleFormatRequest(a))}
                  // internal entries
                {fmt_non_param_edge(a, (), rule_type=GraphVertexType.inner)}
                }}"""
            ).strip(),
            subgraph,
        )

    @pytest.mark.skip(reason="TODO(#10649): figure out if this tests is still relevant.")
    @pytest.mark.no_error_if_skipped
    def test_noop_removal_full_single_subject_type(self) -> None:
        @rule
        async def a_from_c(c: C) -> A:
            return A()

        @rule
        async def a() -> A:
            return A()

        rules = [a_from_c, a, QueryRule(A, (SubA,))]
        fullgraph = self.create_full_graph(rules, validate=False)
        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  /*
                  queries:
                    Query(A for SubA)
                  */
                  // root entries
                {fmt_non_param_edge(A, ())}
                {fmt_non_param_edge(a, (), rule_type=GraphVertexType.singleton)}
                {fmt_non_param_edge(A, (), RuleFormatRequest(a))}
                  // internal entries
                {fmt_non_param_edge(a, (), rule_type=GraphVertexType.inner)}
                }}"""
            ).strip(),
            fullgraph,
        )

    @pytest.mark.skip(reason="TODO(#10649): figure out if this tests is still relevant.")
    @pytest.mark.no_error_if_skipped
    def test_root_tuple_removed_when_no_matches(self) -> None:
        @rule
        async def a_from_c(c: C) -> A:
            return A()

        @rule
        async def b_from_d_and_a(d: D, a: A) -> B:
            return B()

        rules = [
            a_from_c,
            b_from_d_and_a,
        ]

        fullgraph = self.create_full_graph(rules, validate=False)

        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  // root subject types: C, D
                  // root entries
                {fmt_non_param_edge(A, C)}
                {fmt_non_param_edge(A, C, RuleFormatRequest(a_from_c))}
                {fmt_non_param_edge(B, (C, D))}
                {fmt_non_param_edge(B, (C, D), RuleFormatRequest(b_from_d_and_a))}
                  // internal entries
                {fmt_param_edge(C, C, RuleFormatRequest(a_from_c))}
                {fmt_param_edge(D, (C, D), RuleFormatRequest(b_from_d_and_a), return_func=RuleFormatRequest(a_from_c, C))}
                }}"""
            ).strip(),
            fullgraph,
        )

    @pytest.mark.skip(reason="TODO(#10649): figure out if this tests is still relevant.")
    @pytest.mark.no_error_if_skipped
    def test_noop_removal_transitive(self) -> None:
        # If a noop-able rule has rules that depend on it,
        # they should be removed from the graph.

        @rule
        async def b_from_c(c: C) -> B:
            return B()

        @rule
        async def a_from_b(b: B) -> A:
            return A()

        @rule
        async def a() -> A:
            return A()

        rules = [
            b_from_c,
            a_from_b,
            a,
        ]
        subgraph = self.create_subgraph(A, rules, SubA(), validate=False)

        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  // root subject types: SubA
                  // root entries
                {fmt_non_param_edge(A, ())}
                {fmt_non_param_edge(a, (), rule_type=GraphVertexType.singleton)}
                {fmt_non_param_edge(A, (), RuleFormatRequest(a))}
                  // internal entries
                {fmt_non_param_edge(a, (), rule_type=GraphVertexType.inner)}
                }}"""
            ).strip(),
            subgraph,
        )

    def test_matching_singleton(self) -> None:
        @rule
        async def a_from_suba(suba: SubA, b: B) -> A:
            return A()

        @rule
        async def b_singleton() -> B:
            return B()

        rules = [a_from_suba, b_singleton, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA())
        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  /*
                  queries:
                    Query(A for SubA)
                  */
                  // root entries
                {fmt_non_param_edge(A, SubA)}
                {fmt_non_param_edge(A, SubA, RuleFormatRequest(a_from_suba))}
                  // internal entries
                {fmt_non_param_edge(b_singleton, (), rule_type=GraphVertexType.inner)}
                {fmt_non_param_edge(b_singleton, (), rule_type=GraphVertexType.singleton)}
                {fmt_param_edge(SubA, SubA, via_func=RuleFormatRequest(a_from_suba), return_func=RuleFormatRequest(b_singleton, ()))}
                }}"""
            ).strip(),
            subgraph,
        )

    @pytest.mark.skip(reason="TODO(#10649): figure out if this tests is still relevant.")
    @pytest.mark.no_error_if_skipped
    def test_depends_on_multiple_one_noop(self) -> None:
        @rule
        async def a_from_c(c: C) -> A:
            return A()

        @rule
        async def a_from_suba(suba: SubA) -> A:
            return A()

        @rule
        async def b_from_a(a: A) -> B:
            return B()

        rules = [a_from_c, a_from_suba, b_from_a, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(B, rules, SubA(), validate=False)
        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  /*
                  queries:
                    Query(A for SubA)
                  */
                  // root entries
                {fmt_non_param_edge(B, SubA)}
                {fmt_non_param_edge(B, SubA, RuleFormatRequest(b_from_a))}
                  // internal entries
                {fmt_non_param_edge(RuleFormatRequest(b_from_a), SubA, RuleFormatRequest(a_from_suba))}
                {fmt_param_edge(SubA, SubA, RuleFormatRequest(a_from_suba))}
                }}"""
            ).strip(),
            subgraph,
        )

    def test_multiple_depend_on_same_rule(self) -> None:
        @rule
        async def a_from_suba(suba: SubA) -> A:
            return A()

        @rule
        async def b_from_a(a: A) -> B:
            return B()

        @rule
        async def c_from_a(a: A) -> C:
            return C()

        rules = [
            a_from_suba,
            b_from_a,
            c_from_a,
            QueryRule(A, (SubA,)),
            QueryRule(B, (SubA,)),
            QueryRule(C, (SubA,)),
        ]
        fullgraph = self.create_full_graph(rules)
        assert_equal_graph_output(
            dedent(
                f"""\
                digraph {{
                  /*
                  queries:
                    Query(A for SubA),
                    Query(B for SubA),
                    Query(C for SubA)
                  */
                  // root entries
                {fmt_non_param_edge(A, SubA)}
                {fmt_non_param_edge(A, SubA, RuleFormatRequest(a_from_suba))}
                {fmt_non_param_edge(B, SubA)}
                {fmt_non_param_edge(B, SubA, RuleFormatRequest(b_from_a))}
                {fmt_non_param_edge(C, SubA)}
                {fmt_non_param_edge(C, SubA, RuleFormatRequest(c_from_a))}
                  // internal entries
                {fmt_non_param_edge(b_from_a, SubA, RuleFormatRequest(a_from_suba))}
                {fmt_non_param_edge(c_from_a, SubA, RuleFormatRequest(a_from_suba))}
                {fmt_param_edge(SubA, SubA, RuleFormatRequest(a_from_suba))}
                }}"""
            ).strip(),
            fullgraph,
        )

    def create_full_graph(self, rules, validate=True):
        scheduler = create_scheduler(rules, validate=validate)
        return "\n".join(scheduler.rule_graph_visualization())

    def create_subgraph(self, requested_product, rules, subject, validate=True):
        scheduler = create_scheduler(rules, validate=validate)
        return "\n".join(scheduler.rule_subgraph_visualization([type(subject)], requested_product))


def test_duplicated_rules() -> None:
    err = (
        r"Redeclaring rule pants\.engine\.rules_test\.test_duplicated_rules\.dup_a with "
        r"<function test_duplicated_rules\.<locals>\.dup_a at .*> at line \d+, previously defined "
        r"by <function test_duplicated_rules\.<locals>\.dup_a at .*> at line \d+\."
    )
    with pytest.raises(DuplicateRuleError, match=err):

        @rule
        async def dup_a() -> A:
            return A()

        @rule  # type: ignore[no-redef] # noqa: F811
        async def dup_a() -> B:  # noqa: F811
            return B()


def test_param_type_overrides() -> None:
    type1 = int  # use a runtime type

    @rule(_param_type_overrides={"param1": type1, "param2": dict})
    async def dont_injure_humans(param1: str, param2, param3: list) -> A:
        return A()

    dont_injure_humans_rule = dont_injure_humans.rule  # type: ignore[attr-defined]
    assert tuple(dont_injure_humans_rule.parameters.values()) == (int, dict, list)

    with pytest.raises(ValueError, match="paramX"):

        @rule(_param_type_overrides={"paramX": int})
        async def obey_human_orders() -> A:
            return A()

    with pytest.raises(MissingParameterTypeAnnotation, match="must be a type"):

        @rule(_param_type_overrides={"param1": "A string"})  # type: ignore
        async def protect_existence(param1) -> A:
            return A()
