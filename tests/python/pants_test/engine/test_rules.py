# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from collections import OrderedDict
from textwrap import dedent

from pants.base.specs import (AscendantAddresses, DescendantAddresses, SiblingAddresses,
                              SingleAddress)
from pants.build_graph.address import Address
from pants.engine.addressable import Exactly
from pants.engine.fs import PathGlobs, create_fs_tasks
from pants.engine.graph import create_graph_tasks
from pants.engine.mapper import AddressMapper
from pants.engine.rules import GraphMaker, NodeBuilder, Rule, RulesetValidator
from pants.engine.selectors import Select, SelectDependencies, SelectLiteral, SelectProjection
from pants_test.engine.examples.parsers import JsonParser
from pants_test.engine.examples.planners import Goal
from pants_test.engine.test_mapper import TargetTable


def assert_equal_with_printing(test_case, strip, subgraph):

  s = str(subgraph)
  print('Expected:')
  print(strip)
  print('Actual:')
  print(s)
  test_case.assertEqual(strip, s)


class AGoal(Goal):

  @classmethod
  def products(cls):
    return [A]


class IntrinsicProvider(object):
  def __init__(self, intrinsics):
    self.intrinsics = intrinsics

  def as_intrinsics(self):
    return self.intrinsics


class BoringRule(Rule):
  input_selectors = tuple()

  def __init__(self, product_type):
    self._output_product_type = product_type

  @property
  def output_product_type(self):
    return self._output_product_type

  def as_node(self, subject, variants):
    raise Exception('do not expect to be constructed')

  def __repr__(self):
    return '{}({})'.format(type(self).__name__, self.output_product_type.__name__)


class A(object):

  def __repr__(self):
    return 'A()'


class B(object):

  def __repr__(self):
    return 'B()'


class C(object):

  def __repr__(self):
    return 'C()'


class D(object):

  def __repr__(self):
    return 'D()'


def noop(*args):
  pass


class SubA(A):

  def __repr__(self):
    return 'SubA()'


_suba_root_subject_fns = {SubA: lambda p: Select(p)}


class NodeBuilderTest(unittest.TestCase):
  def test_creation_fails_with_bad_declaration_type(self):
    with self.assertRaises(TypeError) as cm:
      NodeBuilder.create([A()])
    self.assertEquals("Unexpected rule type: <class 'pants_test.engine.test_rules.A'>."
                      " Rules either extend Rule, or are 3 elem tuples.",
      str(cm.exception))

  def test_creation_fails_with_intrinsic_that_overwrites_another_intrinsic(self):
    a_provider = IntrinsicProvider({(A, A): BoringRule(A)})
    with self.assertRaises(ValueError):
      NodeBuilder.create([BoringRule(A)], intrinsic_providers=(a_provider, a_provider))


class RulesetValidatorTest(unittest.TestCase):
  def test_ruleset_with_missing_product_type(self):
    rules = [(A, (Select(B),), noop)]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_fns={k: lambda p: Select(p) for k in (SubA,)})
    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, (Select(B),), noop):
                         no matches for Select(B) with subject types: SubA
                     """).strip(),
                                    str(cm.exception))

  def test_ruleset_with_rule_with_two_missing_selects(self):
    rules = [(A, (Select(B), Select(B)), noop)]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_fns={k: lambda p: Select(p) for k in (SubA,)})
    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, (Select(B), Select(B)), noop):
                         no matches for Select(B) with subject types: SubA
                     """).strip(),
      str(cm.exception))

  def test_ruleset_with_with_selector_only_provided_as_root_subject(self):

    validator = RulesetValidator(NodeBuilder.create([(A, (Select(B),), noop)]),
      goal_to_product=dict(),
      root_subject_fns={k: lambda p: Select(p) for k in (B,)})

    validator.validate()

  def test_fails_if_root_subject_types_empty(self):
    rules = [
      (A, (Select(B),), noop),
    ]
    with self.assertRaises(ValueError) as cm:
      RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_fns={})
    self.assertEquals(dedent("""
                                root_subject_fns must not be empty
                             """).strip(), str(cm.exception))

  def test_ruleset_with_superclass_of_selected_type_produced_fails(self):
    rules = [
      (A, (Select(B),), noop),
      (B, (Select(SubA),), noop)
    ]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_fns={k: lambda p: Select(p) for k in (C,)})

    with self.assertRaises(ValueError) as cm:
      validator.validate()
    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 2
                       (B, (Select(SubA),), noop):
                         no matches for Select(SubA) with subject types: C
                       (A, (Select(B),), noop):
                         depends on unfulfillable (B, (Select(SubA),), noop) of C with subject types: C
                     """).strip(),
                                     str(cm.exception))

  def test_ruleset_with_goal_not_produced(self):
    # The graph is complete, but the goal 'goal-name' requests A,
    # which is not produced by any rule.
    rules = [
      (B, (Select(SubA),), noop)
    ]

    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns={k: lambda p: Select(p) for k in (SubA,)})
    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assert_equal_with_printing("no task for product used by goal \"goal-name\": AGoal",
                                    str(cm.exception))

  def test_ruleset_with_explicit_type_constraint(self):
    rules = [
      (Exactly(A), (Select(B),), noop),
      (B, (Select(A),), noop)
    ]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_fns={k: lambda p: Select(p) for k in (SubA,)})

    validator.validate()

  def test_ruleset_with_failure_due_to_incompatible_subject_for_intrinsic(self):
    rules = [
      (D, (Select(C),), noop)
    ]
    validator = RulesetValidator(NodeBuilder.create(rules, intrinsic_providers=(IntrinsicProvider({(B, C): BoringRule(C)}),)),
      goal_to_product=dict(),
      root_subject_fns={k: lambda p: Select(p) for k in (A,)})

    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assert_equal_with_printing(dedent("""
                             Rules with errors: 1
                               (D, (Select(C),), noop):
                                 no matches for Select(C) with subject types: A
                             """).strip(),
                                    str(cm.exception))
  assert_equal_with_printing = assert_equal_with_printing
# and now the in progress graph creation
# TODO should raise if a particular root type can't get to a particular rule?
#      that's the thing that bit Ity with her change.
#      could just warn. :/


class PremadeGraphTest(unittest.TestCase):
  # TODO something with variants
  # TODO HasProducts?

  def test_smallest_full_test(self):
    rules = [
      (Exactly(A), (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns={k: lambda p: Select(p) for k in (SubA,)})
    fullgraph = graphmaker.full_graph()

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: "(Exactly(A), (Select(SubA),), noop) of SubA"
                                 (Exactly(A), (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)

                               }""").strip(), fullgraph)

  def test_full_graph_for_planner_example(self):
    symbol_table_cls = TargetTable
    address_mapper = AddressMapper(symbol_table_cls, JsonParser, '*.BUILD.json')
    tasks = create_graph_tasks(address_mapper, symbol_table_cls) + create_fs_tasks()

    rule_index = NodeBuilder.create(tasks)
    graphmaker = GraphMaker(rule_index,
      root_subject_fns={k: lambda p: Select(p) for k in (Address, # TODO, use the actual fns.
                          PathGlobs,
                          SingleAddress,
                          SiblingAddresses,
                          DescendantAddresses,
                          AscendantAddresses
      )})
    fullgraph = graphmaker.full_graph()
    print('---diagnostic------')
    print(fullgraph.error_message())
    print('/---diagnostic------')
    print(fullgraph)


    # Assert that all of the rules specified the various task fns are present
    declared_rule_strs = set(str(rule) for rules_for_product in rule_index._tasks.values()
                             for rule in rules_for_product)
    declared_intrinsic_strs = set(str(rule) for rule in rule_index._intrinsics.values())

    rules_remaining_in_graph_strs = set(str(r.rule) for r in fullgraph.rule_dependencies.keys())

    self.assertEquals(set(declared_rule_strs.union(declared_intrinsic_strs)),
      rules_remaining_in_graph_strs
    )

    # statically assert that the number of dependency keys is fixed
    self.assertEquals(43, len(fullgraph.rule_dependencies))

  def test_smallest_full_test_multiple_root_subject_types(self):
    rules = [
      (Exactly(A), (Select(SubA),), noop),
      (Exactly(B), (Select(A),), noop)
    ]
    select_p = lambda p: Select(p)
    graphmaker = GraphMaker(NodeBuilder.create(rules, intrinsic_providers=tuple()),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=OrderedDict([(SubA, select_p), (A, select_p)]))
    fullgraph = graphmaker.full_graph()

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject_types: (SubA, A,)
                                 root_rules: "(Exactly(A), (Select(SubA),), noop) of SubA", "(Exactly(B), (Select(A),), noop) of SubA", "SubjectIsProduct(A)", "(Exactly(B), (Select(A),), noop) of A"
                                 (Exactly(A), (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                                 (Exactly(B), (Select(A),), noop) of SubA => ((Exactly(A), (Select(SubA),), noop) of SubA,)
                                 (Exactly(B), (Select(A),), noop) of A => (SubjectIsProduct(A),)

                               }""").strip(), fullgraph)

  def test_single_rule_depending_on_subject_selection(self):
    rules = [
      (Exactly(A), (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (Select(SubA),), noop) of SubA"
                                 (Exactly(A), (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)

                               }""").strip(), subgraph)

  def test_multiple_selects(self):
    rules = [
      (Exactly(A), (Select(SubA), Select(B)), noop),
      (B, tuple(), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (Select(SubA), Select(B)), noop) of SubA"
                                 (Exactly(A), (Select(SubA), Select(B)), noop) of SubA => (SubjectIsProduct(SubA), (B, (), noop) of SubA,)
                                 (B, (), noop) of SubA => (,)

                               }""").strip(), subgraph)

  def test_one_level_of_recursion(self):
    rules = [
      (Exactly(A), (Select(B),), noop),
      (B, (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (Select(B),), noop) of SubA"
                                 (Exactly(A), (Select(B),), noop) of SubA => ((B, (Select(SubA),), noop) of SubA,)
                                 (B, (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)

                               }""").strip(), subgraph)

  def test_noop_removal_in_subgraph(self):
    intrinsics = {(B, C): BoringRule(C)}
    rules = [
      # C is provided by an intrinsic, but only if the subject is B.
      (Exactly(A), (Select(C),), noop),
      (Exactly(A), tuple(), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules,
                                               intrinsic_providers=(IntrinsicProvider(intrinsics),)),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (), noop) of SubA"
                                 (Exactly(A), (), noop) of SubA => (,)

                               }""").strip(), subgraph)

  def test_noop_removal_full_single_subject_type(self):
    intrinsics = {(B, C): BoringRule(C)}
    rules = [
      # C is provided by an intrinsic, but only if the subject is B.
      (Exactly(A), (Select(C),), noop),
      (Exactly(A), tuple(), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules,
      intrinsic_providers=(IntrinsicProvider(intrinsics),)),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    fullgraph = graphmaker.full_graph()

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: "(Exactly(A), (), noop) of SubA"
                                 (Exactly(A), (), noop) of SubA => (,)

                               }""").strip(), fullgraph)

  def test_noop_removal_transitive(self):
    # If a noop-able rule has rules that depend on it,
    # they should be removed from the graph.
    rules = [
      (Exactly(B), (Select(C),), noop),
      (Exactly(A), (Select(B),), noop),
      (Exactly(A), tuple(), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules, (IntrinsicProvider({(D, C): BoringRule(C)}),)),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns,

    )
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (), noop) of SubA"
                                 (Exactly(A), (), noop) of SubA => (,)

                               }""").strip(), subgraph)

  def test_select_dependencies_with_separate_types_for_subselectors(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, C, field_types=(D,)),), noop),
      (B, (Select(D),), noop),
      (C, (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (SelectDependencies(B, C, field_types=(D,)),), noop) of SubA"
                                 (Exactly(A), (SelectDependencies(B, C, field_types=(D,)),), noop) of SubA => ((C, (Select(SubA),), noop) of SubA, (B, (Select(D),), noop) of D,)
                                 (C, (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                                 (B, (Select(D),), noop) of D => (SubjectIsProduct(D),)

                               }""").strip(), subgraph)

  def test_select_dependencies_with_subject_as_first_subselector(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(D,)),), noop),
      (B, (Select(D),), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (SelectDependencies(B, SubA, field_types=(D,)),), noop) of SubA"
                                 (Exactly(A), (SelectDependencies(B, SubA, field_types=(D,)),), noop) of SubA => (SubjectIsProduct(SubA), (B, (Select(D),), noop) of D,)
                                 (B, (Select(D),), noop) of D => (SubjectIsProduct(D),)

                               }""").strip(), subgraph)

  def test_select_dependencies_multiple_field_types_all_resolvable(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop),
      (B, (Select(Exactly(C, D)),), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                                 {
                                   root_subject: SubA()
                                   root_rules: "(Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA"
                                   (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA => (SubjectIsProduct(SubA), (B, (Select(Exactly(C, D)),), noop) of C, (B, (Select(Exactly(C, D)),), noop) of D,)
                                   (B, (Select(Exactly(C, D)),), noop) of C => (SubjectIsProduct(C),)
                                   (B, (Select(Exactly(C, D)),), noop) of D => (SubjectIsProduct(D),)

                                 }""").strip(), subgraph)

  def test_select_dependencies_multiple_field_types_all_resolvable_with_deps(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop),
      # for the C type, it'll just be a literal, but for D, it'll traverse one more edge
      (B, (Select(C),), noop),
      (C, (Select(D),), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                                 {
                                   root_subject: SubA()
                                   root_rules: "(Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA"
                                   (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA => (SubjectIsProduct(SubA), (B, (Select(C),), noop) of C, (B, (Select(C),), noop) of D,)
                                   (B, (Select(C),), noop) of C => (SubjectIsProduct(C),)
                                   (B, (Select(C),), noop) of D => ((C, (Select(D),), noop) of D,)
                                   (C, (Select(D),), noop) of D => (SubjectIsProduct(D),)

                                 }""").strip(), subgraph)

  def test_select_dependencies_recurse_with_different_type(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop),
      (B, (Select(A),), noop),
      (C, (Select(SubA),), noop),
      (SubA, tuple(), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA"
                                 (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA => (SubjectIsProduct(SubA), (B, (Select(A),), noop) of C, (B, (Select(A),), noop) of D,)
                                 (B, (Select(A),), noop) of C => ((Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of C,)
                                 (B, (Select(A),), noop) of D => ((Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of D,)
                                 (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of C => ((SubA, (), noop) of C, (B, (Select(A),), noop) of C, (B, (Select(A),), noop) of D,)
                                 (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of D => ((SubA, (), noop) of D, (B, (Select(A),), noop) of C, (B, (Select(A),), noop) of D,)
                                 (SubA, (), noop) of C => (,)
                                 (SubA, (), noop) of D => (,)

                               }""").strip(), subgraph)

  def test_select_dependencies_non_matching_subselector_because_of_intrinsic(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(D,)),), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules,
      intrinsic_providers=(IntrinsicProvider({(C, B): BoringRule(B)}),)
    ),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing('{empty graph}', subgraph)

  def test_select_dependencies_with_matching_intrinsic(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C,)),), noop),
    ]
    intrinsics = {(C, B): BoringRule(B)}

    graphmaker = GraphMaker(NodeBuilder.create(rules,
      intrinsic_providers=(IntrinsicProvider(intrinsics),)
    ),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (SelectDependencies(B, SubA, field_types=(C,)),), noop) of SubA"
                                 (Exactly(A), (SelectDependencies(B, SubA, field_types=(C,)),), noop) of SubA => (SubjectIsProduct(SubA), BoringRule(B) of C,)
                                 BoringRule(B) of C => (,)

                               }""").strip(), subgraph)

  def test_depends_on_multiple_one_noop(self):
    rules = [
      (B, (Select(A),), noop),
      (A, (Select(C),), noop),
      (A, (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=B)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(B, (Select(A),), noop) of SubA"
                                 (B, (Select(A),), noop) of SubA => ((A, (Select(SubA),), noop) of SubA,)
                                 (A, (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)

                               }""").strip(), subgraph)

  def test_select_literal(self):
    literally_a = A()
    rules = [
      (B, (SelectLiteral(literally_a, A),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=B)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(B, (SelectLiteral(A(), A),), noop) of SubA"
                                 (B, (SelectLiteral(A(), A),), noop) of SubA => (Literal(A(), A),)

                               }""").strip(), subgraph)

  def test_select_projection_simple(self):
    rules = [
      (Exactly(A), (SelectProjection(B, D, ('some',), SubA),), noop),
      (B, (Select(D),), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (SelectProjection(B, D, (u'some',), SubA),), noop) of SubA"
                                 (Exactly(A), (SelectProjection(B, D, (u'some',), SubA),), noop) of SubA => (SubjectIsProduct(SubA), (B, (Select(D),), noop) of D,)
                                 (B, (Select(D),), noop) of D => (SubjectIsProduct(D),)

                               }""").strip(), subgraph)

  def test_initial_select_projection_failure(self):
    rules = [
      (Exactly(A), (SelectProjection(B, D, ('some',), C),), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing('{empty graph}', subgraph)

  def test_secondary_select_projection_failure(self):
    rules = [
      (Exactly(A), (SelectProjection(B, D, ('some',), C),), noop),
      (C, tuple(), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing('{empty graph}', subgraph)

  def test_diagnostic_graph_select_projection(self):
    rules = [
      (Exactly(A), (SelectProjection(B, D, ('some',), C),), noop),
      (C, tuple(), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (Exactly(A), (SelectProjection(B, D, (u'some',), C),), noop):
                         no matches for Select(B) when resolving SelectProjection(B, D, (u'some',), C) with subject types: D
                     """).strip(), subgraph.error_message())

  def test_diagnostic_graph_simple_select_failure(self):
    rules = [
      (Exactly(A), (Select(C),), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               Rules with errors: 1
                                 (Exactly(A), (Select(C),), noop):
                                   no matches for Select(C) with subject types: SubA
                          """).strip(), subgraph.error_message())

  assert_equal_with_printing = assert_equal_with_printing
