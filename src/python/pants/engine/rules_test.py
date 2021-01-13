# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
import re
import unittest
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from textwrap import dedent
from typing import Callable, List, Optional, Tuple, Type, Union, get_type_hints

import pytest

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.engine_testutil import assert_equal_with_printing
from pants.engine.internals.native import Native
from pants.engine.internals.native_engine import PyExecutor
from pants.engine.internals.scheduler import Scheduler
from pants.engine.internals.selectors import GetConstraints, GetParseError
from pants.engine.rules import (
    Get,
    MissingParameterTypeAnnotation,
    MissingReturnTypeAnnotation,
    QueryRule,
    RuleIndex,
    UnrecognizedRuleArgument,
    _RuleVisitor,
    goal_rule,
    rule,
)
from pants.engine.unions import UnionMembership
from pants.option.global_options import DEFAULT_EXECUTION_OPTIONS
from pants.testutil.rule_runner import MockGet, run_rule_with_mocks
from pants.util.enums import match
from pants.util.logging import LogLevel

_EXECUTOR = PyExecutor(2, 4)


def create_scheduler(rules, validate=True, native=None):
    """Create a Scheduler."""
    native = native or Native()
    return Scheduler(
        native=native,
        ignore_patterns=[],
        use_gitignore=False,
        build_root=str(Path.cwd()),
        local_store_dir="./.pants.d/lmdb_store",
        local_execution_root_dir="./.pants.d",
        named_caches_dir="./.pants.d/named_caches",
        ca_certs_path=None,
        rules=rules,
        union_membership=UnionMembership({}),
        executor=_EXECUTOR,
        execution_options=DEFAULT_EXECUTION_OPTIONS,
        validate_reachability=validate,
    )


def fmt_rule(
    rule: Callable, *, gets: Optional[List[Tuple[str, str]]] = None, multiline: bool = False
) -> str:
    """Generate the str that the engine will use for the rule.

    This is useful when comparing strings against engine error messages. Emulates the implementation
    of the DisplayForGraph trait.
    """

    def fmt_rust_function(func: Callable) -> str:
        return f"{func.__module__}:{func.__code__.co_firstlineno}:{func.__name__}"

    line_sep = "\n" if multiline else " "
    optional_line_sep = "\n" if multiline else ""

    type_hints = get_type_hints(rule)
    product = type_hints.pop("return").__name__
    params = f",{line_sep}".join(t.__name__ for t in type_hints.values())
    params_str = (
        f"{optional_line_sep}{params}{optional_line_sep}" if len(type_hints) > 1 else params
    )
    gets_str = ""
    if gets:
        get_members = f",{line_sep}".join(
            f"Get({product_subject_pair[0]}, {product_subject_pair[1]})"
            for product_subject_pair in gets
        )
        gets_str = f", gets=[{optional_line_sep}{get_members}{optional_line_sep}]"
    return f"@rule({fmt_rust_function(rule)}({params_str}) -> {product}{gets_str})"


class RuleVisitorTest(unittest.TestCase):
    @staticmethod
    def _parse_rule_gets(rule_text: str, **types: Type) -> List[GetConstraints]:
        rule_visitor = _RuleVisitor(
            resolve_type=lambda name: types[name], source_file_name="parse_rules.py"
        )
        rule_visitor.visit(ast.parse(rule_text))
        return rule_visitor.gets

    @classmethod
    def _parse_single_get(cls, rule_text: str, **types) -> GetConstraints:
        gets = cls._parse_rule_gets(rule_text, **types)
        assert len(gets) == 1, f"Expected 1 Get expression, found {len(gets)}."
        return gets[0]

    def test_single_get(self) -> None:
        get = self._parse_single_get(
            dedent(
                """
                async def rule():
                    a = await Get(A, B, 42)
                """
            ),
            A=str,
            B=int,
        )
        assert get.output_type == str
        assert get.input_type == int

    def test_multiple_gets(self) -> None:
        gets = self._parse_rule_gets(
            dedent(
                """
                async def rule():
                    a = await Get(A, B, 42)
                    if len(a) > 1:
                        c = await Get(C, A("bob"))
                """
            ),
            A=str,
            B=int,
            C=bool,
        )

        assert len(gets) == 2
        get_a, get_c = gets

        assert get_a.output_type == str
        assert get_a.input_type == int

        assert get_c.output_type == bool
        assert get_c.input_type == str

    def test_multiget_homogeneous(self) -> None:
        get = self._parse_single_get(
            dedent(
                """
                async def rule():
                    a = await MultiGet(Get(A, B(x)) for x in range(5))
                """
            ),
            A=str,
            B=int,
        )
        assert get.output_type == str
        assert get.input_type == int

    def test_multiget_heterogeneous(self) -> None:
        gets = self._parse_rule_gets(
            dedent(
                """
                async def rule():
                    a = await MultiGet(Get(A, B, 42), Get(B, A('bob')))
                """
            ),
            A=str,
            B=int,
        )

        assert len(gets) == 2
        get_a, get_b = gets

        assert get_a.output_type == str
        assert get_a.input_type == int

        assert get_b.output_type == int
        assert get_b.input_type == str

    def test_get_no_index_call_no_subject_call_allowed(self) -> None:
        gets = self._parse_rule_gets("get_type: type = Get")
        assert len(gets) == 0

    def test_valid_get_unresolvable_product_type(self) -> None:
        with pytest.raises(KeyError):
            self._parse_rule_gets("Get(DNE, A(42))", A=int)

    def test_valid_get_unresolvable_subject_declared_type(self) -> None:
        with pytest.raises(KeyError):
            self._parse_rule_gets("Get(int, DNE, 'bob')")

    def test_invalid_get_no_subject_args(self) -> None:
        with pytest.raises(GetParseError):
            self._parse_rule_gets("Get(A, )", A=int)

    def test_invalid_get_too_many_subject_args(self) -> None:
        with pytest.raises(GetParseError):
            self._parse_rule_gets("Get(A, B, 'bob', 3)", A=int, B=str)

    def test_invalid_get_invalid_subject_arg_no_constructor_call(self) -> None:
        with pytest.raises(GetParseError):
            self._parse_rule_gets("Get(A, 'bob')", A=int)

    def test_invalid_get_invalid_product_type_not_a_type_name(self) -> None:
        with pytest.raises(GetParseError):
            self._parse_rule_gets("Get(call(), A('bob'))", A=str)


@dataclass(frozen=True)
class RuleFormatRequest:
    rule: Callable
    for_param: Optional[Union[Type, Tuple[Type, ...]]] = None
    gets: Optional[List[Tuple[str, str]]] = None

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
    param: Type,
    product: Union[Type, Tuple[Type, ...]],
    via_func: Union[Type, RuleFormatRequest],
    return_func: Optional[RuleFormatRequest] = None,
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

    def graph_vertex_color_fmt_str(self) -> Optional[str]:
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
    subject: Union[Type, Callable, RuleFormatRequest],
    product: Union[Type, Tuple[Type, ...]],
    return_func: Optional[RuleFormatRequest] = None,
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
        via_return_func = "-> {" + f'"{return_func_fmt}\nfor {product_name}"' + "}"

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


def assert_equal_graph_output(test_case, expected, actual):
    return assert_equal_with_printing(
        test_case, expected, actual, uniform_formatter=remove_whitespace_from_graph_output
    )


class A:
    def __repr__(self):
        return "A()"


class B:
    def __repr__(self):
        return "B()"


class C:
    def __repr__(self):
        return "C()"


class D:
    def __repr__(self):
        return "D()"


def noop(*args):
    pass


class SubA(A):
    def __repr__(self):
        return "SubA()"


class ExampleSubsystem(GoalSubsystem):
    """An example."""

    name = "example"


class Example(Goal):
    subsystem_cls = ExampleSubsystem


@goal_rule
async def a_goal_rule_generator(console: Console) -> Example:
    a = await Get(A, str("a str!"))
    console.print_stdout(str(a))
    return Example(exit_code=0)


class RuleTest(unittest.TestCase):
    def test_run_rule_goal_rule_generator(self):
        res = run_rule_with_mocks(
            a_goal_rule_generator,
            rule_args=[Console()],
            mock_gets=[MockGet(output_type=A, input_type=str, mock=lambda _: A())],
        )
        self.assertEqual(res, Example(0))

    def test_side_effecting_inputs(self) -> None:
        @goal_rule
        def valid_rule(console: Console, b: str) -> Example:
            return Example(exit_code=0)

        with self.assertRaises(ValueError) as cm:

            @rule
            def invalid_rule(console: Console, b: str) -> bool:
                return False

        error_str = str(cm.exception)
        assert (
            "(@rule pants.engine.rules_test:invalid_rule) has a side-effecting parameter"
            in error_str
        )
        assert "pants.util.meta.Console" in error_str


def test_rule_index_creation_fails_with_bad_declaration_type():
    with pytest.raises(TypeError) as exc:
        RuleIndex.create([A()])
    assert str(exc.value) == (
        "Rule entry A() had an unexpected type: <class 'pants.engine.rules_test.A'>. Rules "
        "either extend Rule or UnionRule, or are static functions decorated with @rule."
    )


class RuleArgumentAnnotationTest(unittest.TestCase):
    def test_annotations_kwargs(self):
        @rule(level=LogLevel.INFO)
        def a_named_rule(a: int, b: str) -> bool:
            return False

        self.assertIsNotNone(a_named_rule.rule)
        self.assertEqual(a_named_rule.rule.canonical_name, "pants.engine.rules_test.a_named_rule")
        self.assertEqual(a_named_rule.rule.desc, None)
        self.assertEqual(a_named_rule.rule.level, LogLevel.INFO)

        @rule(canonical_name="something_different", desc="Human readable desc")
        def another_named_rule(a: int, b: str) -> bool:
            return False

        self.assertIsNotNone(a_named_rule.rule)
        self.assertEqual(another_named_rule.rule.canonical_name, "something_different")
        self.assertEqual(another_named_rule.rule.desc, "Human readable desc")
        self.assertEqual(another_named_rule.rule.level, LogLevel.TRACE)

    def test_bogus_rules(self):
        with self.assertRaises(UnrecognizedRuleArgument):

            @rule(bogus_kwarg="TOTALLY BOGUS!!!!!!")
            def a_named_rule(a: int, b: str) -> bool:
                return False

    def test_goal_rule_automatically_gets_desc_from_goal(self):
        @goal_rule
        def some_goal_rule() -> Example:
            return Example(exit_code=0)

        assert some_goal_rule.rule.desc == "`example` goal"

    def test_can_override_goal_rule_name(self):
        @goal_rule(canonical_name="some_other_name")
        def some_goal_rule() -> Example:
            return Example(exit_code=0)

        name = some_goal_rule.rule.canonical_name
        self.assertEqual(name, "some_other_name")


class GraphVertexTypeAnnotationTest(unittest.TestCase):
    def test_nominal(self):
        @rule
        def dry(a: int, b: str, c: float) -> bool:
            return False

        self.assertIsNotNone(dry.rule)

    def test_missing_return_annotation(self):
        with self.assertRaises(MissingReturnTypeAnnotation):

            @rule
            def dry(a: int, b: str, c: float):
                return False

    def test_bad_return_annotation(self):
        with self.assertRaises(MissingReturnTypeAnnotation):

            @rule
            def dry(a: int, b: str, c: float) -> 42:
                return False

    def test_missing_parameter_annotation(self):
        with self.assertRaises(MissingParameterTypeAnnotation):

            @rule
            def dry(a: int, b, c: float) -> bool:
                return False

    def test_bad_parameter_annotation(self):
        with self.assertRaises(MissingParameterTypeAnnotation):

            @rule
            def dry(a: int, b: 42, c: float) -> bool:
                return False


def test_goal_rule_not_properly_marked_goal_rule() -> None:
    with pytest.raises(TypeError) as exc:

        @rule
        def normal_rule_trying_to_return_a_goal() -> Example:
            return Example(0)

    assert (
        str(exc.value)
        == "An `@rule` that returns a `Goal` must instead be declared with `@goal_rule`."
    )


def test_goal_rule_not_returning_a_goal() -> None:
    with pytest.raises(TypeError) as exc:

        @goal_rule
        def goal_rule_returning_a_non_goal() -> int:
            return 0

    assert str(exc.value) == "An `@goal_rule` must return a subclass of `engine.goal.Goal`."


class RuleGraphTest(unittest.TestCase):
    maxDiff = None

    def test_ruleset_with_ambiguity(self):
        @rule
        def a_from_b_and_c(b: B, c: C) -> A:
            pass

        @rule
        def a_from_c_and_b(c: C, b: B) -> A:
            pass

        rules = [a_from_b_and_c, a_from_c_and_b, QueryRule(A, (B, C))]
        with self.assertRaises(Exception) as cm:
            create_scheduler(rules)

        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                Encountered 1 rule graph error:
                  Too many sources of dependency A for Query(A for (B, C)): [
                        "{fmt_rule(a_from_c_and_b)} (for (B, C))",
                        "{fmt_rule(a_from_b_and_c)} (for (B, C))",
                    ]
                """
            ),
            str(cm.exception),
        )

    def test_ruleset_with_valid_root(self):
        @rule
        def a_from_b(b: B) -> A:
            pass

        rules = [a_from_b, QueryRule(A, (B,))]
        create_scheduler(rules)

    def test_ruleset_with_unreachable_root(self):
        @rule
        def a_from_b(b: B) -> A:
            pass

        rules = [a_from_b, QueryRule(A, ())]
        with self.assertRaises(Exception) as cm:
            create_scheduler(rules)
        assert (
            "No installed rules return the type B, and it was not provided by potential "
            "callers of "
        ) in str(cm.exception)
        assert (
            "If that type should be computed by a rule, ensure that that rule is installed."
        ) in str(cm.exception)
        assert (
            "If it should be provided by a caller, ensure that it is included in any relevant "
            "Query or Get."
        ) in str(cm.exception)

    @pytest.mark.skip(reason="TODO(#10649): figure out if this tests is still relevant.")
    def test_not_fulfillable_duplicated_dependency(self):
        # If a rule depends on another rule+subject in two ways, and one of them is unfulfillable
        # Only the unfulfillable one should be in the errors.

        @rule
        def a_from_c(c: C) -> A:
            pass

        @rule
        def b_from_d(d: D) -> B:
            pass

        @rule
        async def d_from_a_and_suba(a: A, suba: SubA) -> D:  # type: ignore[return]
            _ = await Get(A, C, C())  # noqa: F841

        rules = [
            a_from_c,
            b_from_d,
            d_from_a_and_suba,
        ]

        with self.assertRaises(Exception) as cm:
            create_scheduler(rules)

        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                Rules with errors: 2

                  {fmt_rule(a_from_c)}:
                    Was not reachable, either because no rules could produce the params or because it was shadowed by another @rule.

                  {fmt_rule(d_from_a_and_suba, gets=[("A", "C")])}:
                    No rule was able to compute A.:
                      {fmt_rule(a_from_c)} for SubA: Was unfulfillable.
                """
            ).strip(),
            str(cm.exception),
        )

    @pytest.mark.skip(
        reason="TODO(#10649): Fix and re-enable once reachability checks are restored."
    )
    def test_unreachable_rule(self):
        """Test that when one rule "shadows" another, we get an error."""

        @rule
        def d_singleton() -> D:
            return D()

        @rule
        def d_for_b(b: B) -> D:
            return D()

        rules = [d_singleton, d_for_b, QueryRule(D, (B,))]
        with self.assertRaises(Exception) as cm:
            create_scheduler(rules)

        self.assert_equal_with_printing(
            dedent(
                f"""\
                Rules with errors: 1

                  {fmt_rule(d_for_b)}:
                    Was not reachable, either because no rules could produce the params or because it was shadowed by another @rule.
                """
            ).strip(),
            str(cm.exception),
        )

    def test_smallest_full_test(self):
        @rule
        def a_from_suba(suba: SubA) -> A:
            pass

        rules = [a_from_suba, QueryRule(A, (SubA,))]
        fullgraph = self.create_full_graph(rules)
        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA)
                  // root entries
                {fmt_non_param_edge(A, SubA)}
                {fmt_non_param_edge(A, SubA, RuleFormatRequest(a_from_suba))}
                  // internal entries
                {fmt_param_edge(SubA, SubA, RuleFormatRequest(a_from_suba))}
                }}"""
            ).strip(),
            fullgraph,
        )

    def test_smallest_full_test_multiple_root_subject_types(self):
        @rule
        def a_from_suba(suba: SubA) -> A:
            pass

        @rule
        def b_from_a(a: A) -> B:
            pass

        rules = [a_from_suba, QueryRule(A, (SubA,)), b_from_a, QueryRule(B, (A,))]
        fullgraph = self.create_full_graph(rules)
        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA), Query(B for A)
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

    def test_single_rule_depending_on_subject_selection(self):
        @rule
        def a_from_suba(suba: SubA) -> A:
            pass

        rules = [a_from_suba, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA())
        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA)
                  // root entries
                {fmt_non_param_edge(A, SubA)}
                {fmt_non_param_edge(A, SubA, RuleFormatRequest(a_from_suba))}
                  // internal entries
                {fmt_param_edge(SubA, SubA, RuleFormatRequest(a_from_suba))}
                }}"""
            ).strip(),
            subgraph,
        )

    def test_multiple_selects(self):
        @rule
        def a_from_suba_and_b(suba: SubA, b: B) -> A:
            pass

        @rule
        def b() -> B:
            pass

        rules = [a_from_suba_and_b, b, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA())
        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA)
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

    def test_potentially_ambiguous_get(self):
        # In this case, we validate that a Get is satisfied by a rule that actually consumes its
        # parameter, rather than by having the same dependency rule consume a parameter that was
        # already in the context.
        #
        # This accounts for the fact that when someone uses Get (rather than Select), it's because
        # they intend for the Get's parameter to be consumed in the subgraph. Anything else would
        # be surprising.
        @rule
        async def a(sub_a: SubA) -> A:  # type: ignore[return]
            _ = await Get(B, C())  # noqa: F841

        @rule
        def b_from_suba(suba: SubA) -> B:
            pass

        @rule
        def suba_from_c(c: C) -> SubA:
            pass

        rules = [a, b_from_suba, suba_from_c, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA())
        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA)
                  // root entries
                {fmt_non_param_edge(A, SubA)}
                {fmt_non_param_edge(A, SubA, return_func=RuleFormatRequest(a, gets=[("B", "C")]))}
                  // internal entries
                {fmt_non_param_edge(b_from_suba, C, return_func=RuleFormatRequest(suba_from_c))}
                {fmt_param_edge(C, C, RuleFormatRequest(suba_from_c))}
                {fmt_param_edge(SubA, SubA, via_func=RuleFormatRequest(a, gets=[("B", "C")]), return_func=RuleFormatRequest(b_from_suba, C))}
                }}
                """
            ).strip(),
            subgraph,
        )

    def test_one_level_of_recursion(self):
        @rule
        def a_from_b(b: B) -> A:
            pass

        @rule
        def b_from_suba(suba: SubA) -> B:
            pass

        rules = [a_from_b, b_from_suba, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA())
        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA)
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
    def test_noop_removal_in_subgraph(self):
        @rule
        def a_from_c(c: C) -> A:
            pass

        @rule
        def a() -> A:
            pass

        @rule
        def b_singleton() -> B:
            return B()

        rules = [a_from_c, a, b_singleton, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA(), validate=False)
        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA)
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
    def test_noop_removal_full_single_subject_type(self):
        @rule
        def a_from_c(c: C) -> A:
            pass

        @rule
        def a() -> A:
            pass

        rules = [a_from_c, a, QueryRule(A, (SubA,))]
        fullgraph = self.create_full_graph(rules, validate=False)
        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA)
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
    def test_root_tuple_removed_when_no_matches(self):
        @rule
        def a_from_c(c: C) -> A:
            pass

        @rule
        def b_from_d_and_a(d: D, a: A) -> B:
            pass

        rules = [
            a_from_c,
            b_from_d_and_a,
        ]

        fullgraph = self.create_full_graph(rules, validate=False)

        assert_equal_graph_output(
            self,
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
    def test_noop_removal_transitive(self):
        # If a noop-able rule has rules that depend on it,
        # they should be removed from the graph.

        @rule
        def b_from_c(c: C) -> B:
            pass

        @rule
        def a_from_b(b: B) -> A:
            pass

        @rule
        def a() -> A:
            pass

        rules = [
            b_from_c,
            a_from_b,
            a,
        ]
        subgraph = self.create_subgraph(A, rules, SubA(), validate=False)

        assert_equal_graph_output(
            self,
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

    def test_matching_singleton(self):
        @rule
        def a_from_suba(suba: SubA, b: B) -> A:
            return A()

        @rule
        def b_singleton() -> B:
            return B()

        rules = [a_from_suba, b_singleton, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA())
        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA)
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
    def test_depends_on_multiple_one_noop(self):
        @rule
        def a_from_c(c: C) -> A:
            pass

        @rule
        def a_from_suba(suba: SubA) -> A:
            pass

        @rule
        def b_from_a(a: A) -> B:
            pass

        rules = [a_from_c, a_from_suba, b_from_a, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(B, rules, SubA(), validate=False)
        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA)
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

    def test_multiple_depend_on_same_rule(self):
        @rule
        def a_from_suba(suba: SubA) -> A:
            pass

        @rule
        def b_from_a(a: A) -> B:
            pass

        @rule
        def c_from_a(a: A) -> C:
            pass

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
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA), Query(B for SubA), Query(C for SubA)
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

    @pytest.mark.skip(reason="TODO(#10649): figure out if this tests is still relevant.")
    def test_get_simple(self):
        @rule
        async def a() -> A:  # type: ignore[return]
            _ = await Get(B, D, D())  # noqa: F841

        @rule
        async def b_from_d(d: D) -> B:
            pass

        rules = [a, b_from_d, QueryRule(A, (SubA,))]
        subgraph = self.create_subgraph(A, rules, SubA())
        assert_equal_graph_output(
            self,
            dedent(
                f"""\
                digraph {{
                  // queries: Query(A for SubA)
                  // root entries
                {fmt_non_param_edge(A, ())}
                {fmt_non_param_edge(RuleFormatRequest(a, gets=[("B", "D")]), (), rule_type=GraphVertexType.singleton)}
                {fmt_non_param_edge(A, (), RuleFormatRequest(a, gets=[("B", "D")]))}
                  // internal entries
                {fmt_non_param_edge(RuleFormatRequest(a, (), gets=[("B", "D")]), D, RuleFormatRequest(b_from_d),
                                    append_for_product=False)}
                {fmt_param_edge(D, D, RuleFormatRequest(b_from_d))}
                }}"""
            ).strip(),
            subgraph,
        )

    def create_full_graph(self, rules, validate=True):
        scheduler = create_scheduler(rules, validate=validate)
        return "\n".join(scheduler.rule_graph_visualization())

    def create_subgraph(self, requested_product, rules, subject, validate=True):
        scheduler = create_scheduler(rules, validate=validate)
        return "\n".join(scheduler.rule_subgraph_visualization([type(subject)], requested_product))

    assert_equal_with_printing = assert_equal_with_printing
