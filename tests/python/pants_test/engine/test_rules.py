# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from textwrap import dedent

from pants.engine.build_files import create_graph_rules
from pants.engine.console import Console
from pants.engine.fs import create_fs_rules
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.mapper import AddressMapper
from pants.engine.rules import (
  MissingParameterTypeAnnotation,
  MissingReturnTypeAnnotation,
  RootRule,
  RuleIndex,
  UnrecognizedRuleArgument,
  goal_rule,
  rule,
)
from pants.engine.selectors import Get
from pants.testutil.engine.util import (
  TARGET_TABLE,
  MockGet,
  assert_equal_with_printing,
  create_scheduler,
  run_rule,
)
from pants.testutil.test_base import TestBase
from pants_test.engine.examples.parsers import JsonParser


class A:

  def __repr__(self):
    return 'A()'


class B:

  def __repr__(self):
    return 'B()'


class C:

  def __repr__(self):
    return 'C()'


class D:

  def __repr__(self):
    return 'D()'


def noop(*args):
  pass


class SubA(A):

  def __repr__(self):
    return 'SubA()'


_suba_root_rules = [RootRule(SubA)]


_this_is_not_a_type = 3


class ExampleOptions(GoalSubsystem):
  """An example."""
  name = 'example'


class Example(Goal):
  subsystem_cls = ExampleOptions


@goal_rule
async def a_goal_rule_generator(console: Console) -> Example:
  a = await Get[A](str('a str!'))
  console.print_stdout(str(a))
  return Example(exit_code=0)


class RuleTest(TestBase):
  def test_run_rule_goal_rule_generator(self):
    res = run_rule(
      a_goal_rule_generator,
      rule_args=[Console()],
      mock_gets=[MockGet(product_type=A, subject_type=str, mock=lambda _: A())],
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
    assert "invalid_rule has a side-effecting parameter" in error_str
    assert "pants.engine.console.Console" in error_str


class RuleIndexTest(TestBase):
  def test_creation_fails_with_bad_declaration_type(self):
    with self.assertRaisesWithMessage(
      TypeError,
      "Rule entry A() had an unexpected type: <class "
      "'pants_test.engine.test_rules.A'>. Rules either extend Rule or UnionRule, or "
      "are static functions decorated with @rule."):
      RuleIndex.create([A()])


class RuleArgumentAnnotationTest(unittest.TestCase):
  def test_name_kwarg(self):
    @rule(name='A named rule')
    def named_rule(a: int, b: str) -> bool:
      return False
    self.assertIsNotNone(named_rule.rule)
    self.assertEqual(named_rule.rule.name, "A named rule")

  def test_bogus_rule(self):
    with self.assertRaises(UnrecognizedRuleArgument):
      @rule(bogus_kwarg='TOTALLY BOGUS!!!!!!')
      def named_rule(a: int, b: str) -> bool:
        return False

  def test_goal_rule_automatically_gets_name_from_goal(self):
    @goal_rule
    def some_goal_rule() -> Example:
      return Example(exit_code=0)

    self.assertEqual(some_goal_rule.rule.name, "example")

  def test_can_override_goal_rule_name(self):
    @goal_rule(name='example but **COOLER**')
    def some_goal_rule() -> Example:
      return Example(exit_code=0)

    self.assertEqual(some_goal_rule.rule.name, "example but **COOLER**")


class RuleTypeAnnotationTest(unittest.TestCase):
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


class GoalRuleValidation(TestBase):

  def test_not_properly_marked_goal_rule(self) -> None:
    with self.assertRaisesWithMessage(
      TypeError,
      "An `@rule` that returns a `Goal` must instead be declared with `@goal_rule`."
    ):
      @rule
      def normal_rule_trying_to_return_a_goal() -> Example:
        return Example(0)

  def test_goal_rule_not_returning_a_goal(self) -> None:
    with self.assertRaisesWithMessage(
      TypeError, "An `@goal_rule` must return a subclass of `engine.goal.Goal`."
    ):
      @goal_rule
      def goal_rule_returning_a_non_goal() -> int:
        return 0


class RuleGraphTest(TestBase):
  def test_ruleset_with_missing_product_type(self):
    @rule
    def a_from_b_noop(b: B) -> A:
      pass

    rules = _suba_root_rules + [a_from_b_noop]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(
      dedent(
        f"""\
        Rules with errors: 1
          Rule({__name__}.a_from_b_noop(B) -> A):
            No rule was available to compute B with parameter type SubA
        """).strip(),
      str(cm.exception),
    )

  def test_ruleset_with_ambiguity(self):
    @rule
    def a_from_c_and_b(c: C, b: B) -> A:
      pass

    @rule
    def a_from_b_and_c(b: B, c: C) -> A:
      pass

    @rule
    def d_from_a(a: A) -> D:
      pass

    rules = [
        a_from_c_and_b,
        a_from_b_and_c,
        RootRule(B),
        RootRule(C),
        # TODO: Without a rule triggering the selection of A, we don't detect ambiguity here.
        d_from_a,
      ]
    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(
      dedent(
        f"""\
        Rules with errors: 3
          Rule({__name__}.a_from_b_and_c(B, C) -> A):
            Was not reachable, either because no rules can produce the params or it was shadowed by another @rule.
          Rule({__name__}.a_from_c_and_b(C, B) -> A):
            Was not reachable, either because no rules can produce the params or it was shadowed by another @rule.
          Rule({__name__}.d_from_a(A) -> D):
            Ambiguous rules to compute A with parameter types (B, C):
              Rule({__name__}.a_from_b_and_c(B, C) -> A) for (B, C)
              Rule({__name__}.a_from_c_and_b(C, B) -> A) for (B, C)
       """
      ).strip(),
      str(cm.exception),
    )

  def test_ruleset_with_rule_with_two_missing_selects(self):
    @rule
    def a_from_b_and_c(b: B, c: C) -> A:
      pass

    rules = _suba_root_rules + [a_from_b_and_c]
    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(
      dedent(
        f"""\
        Rules with errors: 1
          Rule({__name__}.a_from_b_and_c(B, C) -> A):
            No rule was available to compute B with parameter type SubA
            No rule was available to compute C with parameter type SubA
        """
      ).strip(),
      str(cm.exception),
    )

  def test_ruleset_with_selector_only_provided_as_root_subject(self):
    @rule
    def a_from_b(b: B) -> A:
      pass

    rules = [RootRule(B), a_from_b]
    create_scheduler(rules)

  def test_ruleset_with_superclass_of_selected_type_produced_fails(self):
    @rule
    def a_from_b(b: B) -> A:
      pass

    @rule
    def b_from_suba(suba: SubA) -> B:
      pass

    rules = [
      RootRule(C),
      a_from_b,
      b_from_suba,
    ]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)
    self.assert_equal_with_printing(
      dedent(
        f"""\
        Rules with errors: 2
          Rule({__name__}.a_from_b(B) -> A):
            No rule was available to compute B with parameter type C
          Rule({__name__}.b_from_suba(SubA) -> B):
            No rule was available to compute SubA with parameter type C
        """
      ).strip(),
      str(cm.exception),
    )

  def test_ruleset_with_failure_due_to_incompatible_subject_for_singleton(self):
    @rule
    def d_from_c(c: C) -> D:
      pass

    @rule
    def b_singleton() -> B:
      return B()

    rules = [
      RootRule(A),
      d_from_c,
      b_singleton,
    ]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    # This error message could note near matches like the singleton.
    self.assert_equal_with_printing(
      dedent(
        f"""\
        Rules with errors: 1
          Rule({__name__}.d_from_c(C) -> D):
            No rule was available to compute C with parameter type A
        """).strip(),
        str(cm.exception),
    )

  def test_not_fulfillable_duplicated_dependency(self):
    # If a rule depends on another rule+subject in two ways, and one of them is unfulfillable
    # Only the unfulfillable one should be in the errors.

    @rule
    def b_from_d(d: D) -> B:
      pass

    @rule
    async def d_from_a_and_suba(a: A, suba: SubA) -> D:  # type: ignore[return]
      _ = await Get[A](C, C())  # noqa: F841

    @rule
    def a_from_c(c: C) -> A:
      pass

    rules = _suba_root_rules + [
      b_from_d,
      d_from_a_and_suba,
      a_from_c,
    ]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(
      dedent(
        f"""\
        Rules with errors: 3
          Rule({__name__}.a_from_c(C) -> A):
            Was not reachable, either because no rules can produce the params or it was shadowed by another @rule.
          Rule({__name__}.b_from_d(D) -> B):
            No rule was available to compute D with parameter type SubA
          Rule({__name__}.d_from_a_and_suba(A, SubA) -> D, gets=[Get(A, C)]):
            No rule was available to compute A with parameter type SubA
        """
      ).strip(),
      str(cm.exception),
    )

  def test_unreachable_rule(self):
    """Test that when one rule "shadows" another, we get an error."""
    @rule
    def d_singleton() -> D:
      return D()

    @rule
    def d_for_b(b: B) -> D:
      return D()

    rules = [
      d_singleton,
      d_for_b,
      RootRule(B),
    ]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(
      dedent(
        f"""\
        Rules with errors: 1
          Rule({__name__}.d_for_b(B) -> D):
            Was not reachable, either because no rules can produce the params or it was shadowed by another @rule.
        """
      ).strip(),
      str(cm.exception)
    )

  def test_smallest_full_test(self):
    @rule
    def a_from_suba(suba: SubA) -> A:
      pass

    rules = _suba_root_rules + [
      RootRule(SubA),
      a_from_suba,
    ]
    fullgraph = self.create_full_graph(rules)

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: SubA
          // root entries
            "Select(A) for SubA" [color=blue]
            "Select(A) for SubA" -> {{"Rule({__name__}.a_from_suba(SubA) -> A) for SubA"}}
          // internal entries
            "Rule({__name__}.a_from_suba(SubA) -> A) for SubA" -> {{"Param(SubA)"}}
        }}"""
      ).strip(),
      fullgraph,
    )

  def test_full_graph_for_planner_example(self):
    address_mapper = AddressMapper(JsonParser(TARGET_TABLE), '*.BUILD.json')
    rules = create_graph_rules(address_mapper) + create_fs_rules()

    fullgraph_str = self.create_full_graph(rules)

    print('---diagnostic------')
    print(fullgraph_str)
    print('/---diagnostic------')

    in_root_rules = False
    in_all_rules = False
    all_rules = []
    root_rule_lines = []
    for line in fullgraph_str.splitlines():
      if line.startswith('  // root subject types:'):
        pass
      elif line.startswith('  // root entries'):
        in_root_rules = True
      elif line.startswith('  // internal entries'):
        in_all_rules = True
      elif in_all_rules:
        all_rules.append(line)
      elif in_root_rules:
        root_rule_lines.append(line)
      else:
        pass

    self.assertTrue(6 < len(all_rules))
    self.assertTrue(12 < len(root_rule_lines)) # 2 lines per entry

  def test_smallest_full_test_multiple_root_subject_types(self):
    @rule
    def a_from_suba(suba: SubA) -> A:
      pass

    @rule
    def b_from_a(a: A) -> B:
      pass

    rules = [
      RootRule(SubA),
      RootRule(A),
      a_from_suba,
      b_from_a,
    ]
    fullgraph = self.create_full_graph(rules)
    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: A, SubA
          // root entries
            "Select(A) for A" [color=blue]
            "Select(A) for A" -> {{"Param(A)"}}
            "Select(A) for SubA" [color=blue]
            "Select(A) for SubA" -> {{"Rule({__name__}.a_from_suba(SubA) -> A) for SubA"}}
            "Select(B) for A" [color=blue]
            "Select(B) for A" -> {{"Rule({__name__}.b_from_a(A) -> B) for A"}}
            "Select(B) for SubA" [color=blue]
            "Select(B) for SubA" -> {{"Rule({__name__}.b_from_a(A) -> B) for SubA"}}
          // internal entries
            "Rule({__name__}.a_from_suba(SubA) -> A) for SubA" -> {{"Param(SubA)"}}
            "Rule({__name__}.b_from_a(A) -> B) for A" -> {{"Param(A)"}}
            "Rule({__name__}.b_from_a(A) -> B) for SubA" -> {{"Rule({__name__}.a_from_suba(SubA) -> A) for SubA"}}
        }}"""
      ).strip(),
      fullgraph,
    )

  def test_single_rule_depending_on_subject_selection(self):
    @rule
    def a_from_suba(suba: SubA) -> A:
      pass

    rules = [
      a_from_suba,
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: SubA
          // root entries
            "Select(A) for SubA" [color=blue]
            "Select(A) for SubA" -> {{"Rule({__name__}.a_from_suba(SubA) -> A) for SubA"}}
          // internal entries
            "Rule({__name__}.a_from_suba(SubA) -> A) for SubA" -> {{"Param(SubA)"}}
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

    rules = [
      a_from_suba_and_b,
      b,
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: SubA
          // root entries
            "Select(A) for SubA" [color=blue]
            "Select(A) for SubA" -> {{"Rule({__name__}.a_from_suba_and_b(SubA, B) -> A) for SubA"}}
          // internal entries
            "Rule({__name__}.a_from_suba_and_b(SubA, B) -> A) for SubA" -> {{"Param(SubA)" "Rule({__name__}.b() -> B) for ()"}}
            "Rule({__name__}.b() -> B) for ()" -> {{}}
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
      _ = await Get[B](C())  # noqa: F841

    @rule
    def b_from_suba(suba: SubA) -> B:
      pass

    @rule
    def suba_from_c(c: C) -> SubA:
      pass

    rules = [
      a,
      b_from_suba,
      suba_from_c,
    ]

    subgraph = self.create_subgraph(A, rules, SubA())
    self.assert_equal_with_printing(
        dedent(f"""\
            digraph {{
              // root subject types: SubA
              // root entries
                "Select(A) for SubA" [color=blue]
                "Select(A) for SubA" -> {{"Rule({__name__}.a(SubA) -> A, gets=[Get(B, C)]) for SubA"}}
              // internal entries
                "Rule({__name__}.a(SubA) -> A, gets=[Get(B, C)]) for SubA" -> {{"Param(SubA)" "Rule({__name__}.b_from_suba(SubA) -> B) for C"}}
                "Rule({__name__}.b_from_suba(SubA) -> B) for C" -> {{"Rule({__name__}.suba_from_c(C) -> SubA) for C"}}
                "Rule({__name__}.b_from_suba(SubA) -> B) for SubA" -> {{"Param(SubA)"}}
                "Rule({__name__}.suba_from_c(C) -> SubA) for C" -> {{"Param(C)"}}
            }}
        """).strip(),
        subgraph,
      )

  def test_one_level_of_recursion(self):
    @rule
    def a_from_b(b: B) -> A:
      pass

    @rule
    def b_from_suba(suba: SubA) -> B:
      pass

    rules = [
      a_from_b,
      b_from_suba,
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: SubA
          // root entries
            "Select(A) for SubA" [color=blue]
            "Select(A) for SubA" -> {{"Rule({__name__}.a_from_b(B) -> A) for SubA"}}
          // internal entries
            "Rule({__name__}.a_from_b(B) -> A) for SubA" -> {{"Rule({__name__}.b_from_suba(SubA) -> B) for SubA"}}
            "Rule({__name__}.b_from_suba(SubA) -> B) for SubA" -> {{"Param(SubA)"}}
        }}"""
      ).strip(),
      subgraph,
    )

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

    rules = [
      a_from_c,
      a,
      b_singleton,
    ]

    subgraph = self.create_subgraph(A, rules, SubA(), validate=False)

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: SubA
          // root entries
            "Select(A) for ()" [color=blue]
            "Select(A) for ()" -> {{"Rule({__name__}.a() -> A) for ()"}}
          // internal entries
            "Rule({__name__}.a() -> A) for ()" -> {{}}
        }}"""
      ).strip(),
      subgraph,
    )

  def test_noop_removal_full_single_subject_type(self):
    @rule
    def a_from_c(c: C) -> A:
      pass

    @rule
    def a() -> A:
      pass

    rules = _suba_root_rules + [
      a_from_c,
      a,
    ]

    fullgraph = self.create_full_graph(rules, validate=False)

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: SubA
          // root entries
            "Select(A) for ()" [color=blue]
            "Select(A) for ()" -> {{"Rule({__name__}.a() -> A) for ()"}}
          // internal entries
            "Rule({__name__}.a() -> A) for ()" -> {{}}
        }}"""
      ).strip(),
      fullgraph,
    )

  def test_root_tuple_removed_when_no_matches(self):
    @rule
    def a_from_c(c: C) -> A:
      pass

    @rule
    def b_from_d_and_a(d: D, a: A) -> B:
      pass

    rules = [
      RootRule(C),
      RootRule(D),
      a_from_c,
      b_from_d_and_a,
    ]

    fullgraph = self.create_full_graph(rules, validate=False)

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: C, D
          // root entries
            "Select(A) for C" [color=blue]
            "Select(A) for C" -> {{"Rule({__name__}.a_from_c(C) -> A) for C"}}
            "Select(B) for (C, D)" [color=blue]
            "Select(B) for (C, D)" -> {{"Rule({__name__}.b_from_d_and_a(D, A) -> B) for (C, D)"}}
          // internal entries
            "Rule({__name__}.a_from_c(C) -> A) for C" -> {{"Param(C)"}}
            "Rule({__name__}.b_from_d_and_a(D, A) -> B) for (C, D)" -> {{"Param(D)" "Rule({__name__}.a_from_c(C) -> A) for C"}}
        }}"""
      ).strip(),
      fullgraph,
    )

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

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: SubA
          // root entries
            "Select(A) for ()" [color=blue]
            "Select(A) for ()" -> {{"Rule({__name__}.a() -> A) for ()"}}
          // internal entries
            "Rule({__name__}.a() -> A) for ()" -> {{}}
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

    rules = [
      a_from_suba,
      b_singleton,
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: SubA
          // root entries
            "Select(A) for SubA" [color=blue]
            "Select(A) for SubA" -> {{"Rule({__name__}.a_from_suba(SubA, B) -> A) for SubA"}}
          // internal entries
            "Rule({__name__}.a_from_suba(SubA, B) -> A) for SubA" -> {{"Param(SubA)" "Rule({__name__}.b_singleton() -> B) for ()"}}
            "Rule({__name__}.b_singleton() -> B) for ()" -> {{}}
        }}"""
      ).strip(),
      subgraph,
    )

  def test_depends_on_multiple_one_noop(self):
    @rule
    def b_from_a(a: A) -> B:
      pass

    @rule
    def a_from_c(c: C) -> A:
      pass

    @rule
    def a_from_suba(suba: SubA) -> A:
      pass

    rules = [
     b_from_a,
      a_from_c,
      a_from_suba,
    ]

    subgraph = self.create_subgraph(B, rules, SubA(), validate=False)

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: SubA
          // root entries
            "Select(B) for SubA" [color=blue]
            "Select(B) for SubA" -> {{"Rule({__name__}.b_from_a(A) -> B) for SubA"}}
          // internal entries
            "Rule({__name__}.a_from_suba(SubA) -> A) for SubA" -> {{"Param(SubA)"}}
            "Rule({__name__}.b_from_a(A) -> B) for SubA" -> {{"Rule({__name__}.a_from_suba(SubA) -> A) for SubA"}}
        }}"""
      ).strip(),
      subgraph,
    )

  def test_multiple_depend_on_same_rule(self):
    @rule
    def b_from_a(a: A) -> B:
      pass

    @rule
    def c_from_a(a: A) -> C:
      pass

    @rule
    def a_from_suba(suba: SubA) -> A:
      pass

    rules = _suba_root_rules + [
      b_from_a,
      c_from_a,
      a_from_suba,
    ]

    subgraph = self.create_full_graph(rules)

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: SubA
          // root entries
            "Select(A) for SubA" [color=blue]
            "Select(A) for SubA" -> {{"Rule({__name__}.a_from_suba(SubA) -> A) for SubA"}}
            "Select(B) for SubA" [color=blue]
            "Select(B) for SubA" -> {{"Rule({__name__}.b_from_a(A) -> B) for SubA"}}
            "Select(C) for SubA" [color=blue]
            "Select(C) for SubA" -> {{"Rule({__name__}.c_from_a(A) -> C) for SubA"}}
          // internal entries
            "Rule({__name__}.a_from_suba(SubA) -> A) for SubA" -> {{"Param(SubA)"}}
            "Rule({__name__}.b_from_a(A) -> B) for SubA" -> {{"Rule({__name__}.a_from_suba(SubA) -> A) for SubA"}}
            "Rule({__name__}.c_from_a(A) -> C) for SubA" -> {{"Rule({__name__}.a_from_suba(SubA) -> A) for SubA"}}
        }}"""
      ).strip(),
      subgraph,
    )

  def test_get_simple(self):
    @rule
    async def a() -> A:  # type: ignore[return]
      _ = await Get[B](D, D())  # noqa: F841

    @rule
    async def b_from_d(d: D) -> B:
      pass

    rules = [
      a,
      b_from_d,
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(
      dedent(
        f"""\
        digraph {{
          // root subject types: SubA
          // root entries
            "Select(A) for ()" [color=blue]
            "Select(A) for ()" -> {{"Rule({__name__}.a() -> A, gets=[Get(B, D)]) for ()"}}
          // internal entries
            "Rule({__name__}.a() -> A, gets=[Get(B, D)]) for ()" -> {{"Rule({__name__}.b_from_d(D) -> B) for D"}}
            "Rule({__name__}.b_from_d(D) -> B) for D" -> {{"Param(D)"}}
        }}"""
      ).strip(),
      subgraph,
    )

  def test_invalid_get_arguments(self):
    with self.assertRaisesWithMessage(
      ValueError,
      "Could not resolve type `XXX` in top level of module pants_test.engine.test_rules",
    ):
      class XXX: pass

      @rule
      async def f() -> A:
        return await Get[A](XXX, 3)

    # This fails because the argument is defined in this file's module, but it is not a type.
    with self.assertRaisesWithMessage(
      ValueError,
      "Expected a `type` constructor for `_this_is_not_a_type`, but got: 3 (type `int`)"
    ):
      @rule
      async def g() -> A:
        return await Get(A, _this_is_not_a_type, 3)

  def create_full_graph(self, rules, validate=True):
    scheduler = create_scheduler(rules, validate=validate)
    return "\n".join(scheduler.rule_graph_visualization())

  def create_subgraph(self, requested_product, rules, subject, validate=True):
    scheduler = create_scheduler(rules + _suba_root_rules, validate=validate)
    return "\n".join(scheduler.rule_subgraph_visualization(type(subject), requested_product))

  assert_equal_with_printing = assert_equal_with_printing
