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
from pants.engine.build_files import create_graph_tasks
from pants.engine.fs import PathGlobs, create_fs_intrinsics, create_fs_tasks
from pants.engine.mapper import AddressMapper
from pants.engine.rules import GraphMaker, Rule, RuleIndex, RulesetValidator
from pants.engine.selectors import Select, SelectDependencies, SelectLiteral, SelectProjection
from pants_test.engine.examples.parsers import JsonParser
from pants_test.engine.examples.planners import Goal
from pants_test.engine.test_mapper import TargetTable


def assert_equal_with_printing(test_case, expected, actual):

  str_actual = str(actual)
  print('Expected:')
  print(expected)
  print('Actual:')
  print(str_actual)
  test_case.assertEqual(expected, str_actual)


class AGoal(Goal):

  @classmethod
  def products(cls):
    return [A]


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


class BoringRule(Rule):
  input_selectors = tuple()
  func = noop

  def __init__(self, product_type):
    self._output_product_type = product_type

  @property
  def output_product_type(self):
    return self._output_product_type

  def __repr__(self):
    return '{}({})'.format(type(self).__name__, self.output_product_type.__name__)


class RuleIndexTest(unittest.TestCase):
  def test_creation_fails_with_bad_declaration_type(self):
    with self.assertRaises(TypeError) as cm:
      RuleIndex.create([A()], tuple())
    self.assertEquals("Unexpected rule type: <class 'pants_test.engine.test_rules.A'>."
                      " Rules either extend Rule, or are 3 elem tuples.",
      str(cm.exception))

  def test_creation_fails_with_intrinsic_that_overwrites_another_intrinsic(self):
    a_provider = (A, A, noop)
    with self.assertRaises(ValueError):
      RuleIndex.create([BoringRule(A)], (a_provider, a_provider))


class RulesetValidatorTest(unittest.TestCase):
  def test_ruleset_with_missing_product_type(self):
    rules = [(A, (Select(B),), noop)]
    validator = RulesetValidator(RuleIndex.create(rules, tuple()),
      goal_to_product={},
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
    rules = [(A, (Select(B), Select(C)), noop)]
    validator = RulesetValidator(RuleIndex.create(rules, tuple()),
      goal_to_product={},
      root_subject_fns={k: lambda p: Select(p) for k in (SubA,)})
    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, (Select(B), Select(C)), noop):
                         no matches for Select(B) with subject types: SubA
                         no matches for Select(C) with subject types: SubA
                     """).strip(),
      str(cm.exception))

  def test_ruleset_with_selector_only_provided_as_root_subject(self):
    rules = [(A, (Select(B),), noop)]
    validator = RulesetValidator(RuleIndex.create(rules, tuple()),
      goal_to_product={},
      root_subject_fns={k: lambda p: Select(p) for k in (B,)})

    validator.validate()

  def test_fails_if_root_subject_types_empty(self):
    rules = [
      (A, (Select(B),), noop),
    ]
    with self.assertRaises(ValueError) as cm:
      RulesetValidator(RuleIndex.create(rules, tuple()),
      goal_to_product={},
      root_subject_fns={})
    self.assertEquals(dedent("""
                                root_subject_fns must not be empty
                             """).strip(), str(cm.exception))

  def test_ruleset_with_superclass_of_selected_type_produced_fails(self):
    rules = [
      (A, (Select(B),), noop),
      (B, (Select(SubA),), noop)
    ]
    validator = RulesetValidator(RuleIndex.create(rules, tuple()),
      goal_to_product={},
      root_subject_fns={k: lambda p: Select(p) for k in (C,)})

    with self.assertRaises(ValueError) as cm:
      validator.validate()
    self.assert_equal_with_printing(dedent("""
                                      Rules with errors: 2
                                        (A, (Select(B),), noop):
                                          depends on unfulfillable (B, (Select(SubA),), noop) of C with subject types: C
                                        (B, (Select(SubA),), noop):
                                          no matches for Select(SubA) with subject types: C
                                      """).strip(),
                                    str(cm.exception))

  def test_ruleset_with_goal_not_produced(self):
    # The graph is complete, but the goal 'goal-name' requests A,
    # which is not produced by any rule.
    rules = [
      (B, (Select(SubA),), noop)
    ]

    validator = RulesetValidator(RuleIndex.create(rules, tuple()),
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
    validator = RulesetValidator(RuleIndex.create(rules, tuple()),
      goal_to_product={},
      root_subject_fns={k: lambda p: Select(p) for k in (SubA,)})

    validator.validate()

  def test_ruleset_with_failure_due_to_incompatible_subject_for_intrinsic(self):
    rules = [
      (D, (Select(C),), noop)
    ]
    intrinsics = [
      (B, C, noop),
    ]
    validator = RulesetValidator(RuleIndex.create(rules, intrinsics),
      goal_to_product={},
      root_subject_fns={k: lambda p: Select(p) for k in (A,)})

    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assert_equal_with_printing(dedent("""
                                      Rules with errors: 1
                                        (D, (Select(C),), noop):
                                          no matches for Select(C) with subject types: A
                                      """).strip(),
                                    str(cm.exception))

  def test_ruleset_unreachable_due_to_product_of_select_dependencies(self):
    rules = [
      (A, (SelectDependencies(B, SubA, field_types=(D,)),), noop),
    ]
    intrinsics = [
      (B, C, noop),
    ]
    validator = RulesetValidator(RuleIndex.create(rules, intrinsics),
      goal_to_product={},
      root_subject_fns={k: lambda p: Select(p) for k in (A,)})

    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assert_equal_with_printing(dedent("""
                             Rules with errors: 1
                               (A, (SelectDependencies(B, SubA, u'dependencies', field_types=(D,)),), noop):
                                 Unreachable with subject types: Any
                             """).strip(),
                                    str(cm.exception))

  def test_not_fulfillable_duplicated_dependency(self):
    # If a rule depends on another rule+subject in two ways, and one of them is unfulfillable
    # Only the unfulfillable one should be in the errors.
    rules = [
      (B, (Select(D),), noop),
      (D, (Select(A), SelectDependencies(A, SubA, field_types=(C,))), noop),
      (A, (Select(SubA),), noop)
    ]
    validator = RulesetValidator(RuleIndex.create(rules, tuple()),
      goal_to_product={},
      root_subject_fns=_suba_root_subject_fns)

    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assert_equal_with_printing(dedent("""
                      Rules with errors: 2
                        (B, (Select(D),), noop):
                          depends on unfulfillable (D, (Select(A), SelectDependencies(A, SubA, u'dependencies', field_types=(C,))), noop) of SubA with subject types: SubA
                        (D, (Select(A), SelectDependencies(A, SubA, u'dependencies', field_types=(C,))), noop):
                          depends on unfulfillable (A, (Select(SubA),), noop) of C with subject types: SubA""").strip(),
        str(cm.exception))

  def test_initial_select_projection_failure(self):
    rules = [
      (Exactly(A), (SelectProjection(B, D, ('some',), C),), noop),
    ]
    validator = RulesetValidator(RuleIndex.create(rules, tuple()),
      goal_to_product={},
      root_subject_fns=_suba_root_subject_fns)

    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assert_equal_with_printing(dedent("""
                      Rules with errors: 1
                        (Exactly(A), (SelectProjection(B, D, (u'some',), C),), noop):
                          no matches for Select(C) when resolving SelectProjection(B, D, (u'some',), C) with subject types: SubA
                      """).strip(),
                                    str(cm.exception))

  def test_secondary_select_projection_failure(self):
    rules = [
      (Exactly(A), (SelectProjection(B, D, ('some',), C),), noop),
      (C, tuple(), noop)
    ]

    validator = RulesetValidator(RuleIndex.create(rules, tuple()),
      goal_to_product={},
      root_subject_fns=_suba_root_subject_fns)

    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assert_equal_with_printing(dedent("""
                      Rules with errors: 1
                        (Exactly(A), (SelectProjection(B, D, (u'some',), C),), noop):
                          no matches for Select(B) when resolving SelectProjection(B, D, (u'some',), C) with subject types: D
                      """).strip(),
                                    str(cm.exception))

  assert_equal_with_printing = assert_equal_with_printing
# TODO should it raise if a particular root type can't get to a particular rule? Leaning towards
# no because it may be that there are some subgraphs particular to a particular root subject.


class RuleGraphMakerTest(unittest.TestCase):
  # TODO something with variants
  # TODO HasProducts?

  def test_smallest_full_test(self):
    rules = [
      (Exactly(A), (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns={k: lambda p: Select(p) for k in (SubA,)})
    fullgraph = graphmaker.full_graph()

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: (Exactly(A), (Select(SubA),), noop) of SubA
                                 (Exactly(A), (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                               }""").strip(), fullgraph)

  def test_full_graph_for_planner_example(self):
    symbol_table_cls = TargetTable
    address_mapper = AddressMapper(symbol_table_cls, JsonParser, '*.BUILD.json')
    tasks = create_graph_tasks(address_mapper, symbol_table_cls) + create_fs_tasks()
    intrinsics = create_fs_intrinsics('Let us pretend that this is a ProjectTree!')

    rule_index = RuleIndex.create(tasks, intrinsics)
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
    declared_rules = rule_index.all_rules()
    rules_remaining_in_graph_strs = set(str(r.rule) for r in fullgraph.rule_dependencies.keys())

    declared_rule_strings = set(str(r) for r in declared_rules)
    self.assertEquals(declared_rule_strings,
      rules_remaining_in_graph_strs
    )

  def test_smallest_full_test_multiple_root_subject_types(self):
    rules = [
      (Exactly(A), (Select(SubA),), noop),
      (Exactly(B), (Select(A),), noop)
    ]
    select_p = lambda p: Select(p)
    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=OrderedDict([(SubA, select_p), (A, select_p)]))
    fullgraph = graphmaker.full_graph()

    self.assert_equal_with_printing(dedent("""
                                      {
                                        root_subject_types: (SubA, A,)
                                        root_rules: (Exactly(A), (Select(SubA),), noop) of SubA, (Exactly(B), (Select(A),), noop) of A, (Exactly(B), (Select(A),), noop) of SubA, SubjectIsProduct(A)
                                        (Exactly(A), (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                                        (Exactly(B), (Select(A),), noop) of A => (SubjectIsProduct(A),)
                                        (Exactly(B), (Select(A),), noop) of SubA => ((Exactly(A), (Select(SubA),), noop) of SubA,)
                                      }""").strip(),
                                    fullgraph)

  def test_single_rule_depending_on_subject_selection(self):
    rules = [
      (Exactly(A), (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: (Exactly(A), (Select(SubA),), noop) of SubA
                                 (Exactly(A), (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                               }""").strip(), subgraph)

  def test_multiple_selects(self):
    rules = [
      (Exactly(A), (Select(SubA), Select(B)), noop),
      (B, tuple(), noop)
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                                      {
                                        root_subject_types: (SubA,)
                                        root_rules: (Exactly(A), (Select(SubA), Select(B)), noop) of SubA
                                        (B, (), noop) of SubA => (,)
                                        (Exactly(A), (Select(SubA), Select(B)), noop) of SubA => (SubjectIsProduct(SubA), (B, (), noop) of SubA,)
                                      }""").strip(),
                                    subgraph)

  def test_one_level_of_recursion(self):
    rules = [
      (Exactly(A), (Select(B),), noop),
      (B, (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: (Exactly(A), (Select(B),), noop) of SubA
                                 (B, (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                                 (Exactly(A), (Select(B),), noop) of SubA => ((B, (Select(SubA),), noop) of SubA,)
                               }""").strip(), subgraph)

  def test_noop_removal_in_subgraph(self):
    rules = [
      # C is provided by an intrinsic, but only if the subject is B.
      (Exactly(A), (Select(C),), noop),
      (Exactly(A), tuple(), noop),
    ]
    intrinsics = [
      (B, C, noop),
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules,
                                               intrinsics),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: (Exactly(A), (), noop) of SubA
                                 (Exactly(A), (), noop) of SubA => (,)
                               }""").strip(), subgraph)

  def test_noop_removal_full_single_subject_type(self):
    rules = [
      # C is provided by an intrinsic, but only if the subject is B.
      (Exactly(A), (Select(C),), noop),
      (Exactly(A), tuple(), noop),
    ]
    intrinsics = [
      (B, C, BoringRule(C)),
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, intrinsics),
                            root_subject_fns=_suba_root_subject_fns)
    fullgraph = graphmaker.full_graph()

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: (Exactly(A), (), noop) of SubA
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
    intrinsics = [
      (D, C, BoringRule(C))
    ]
    graphmaker = GraphMaker(RuleIndex.create(rules, intrinsics),
      root_subject_fns=_suba_root_subject_fns,

    )
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: (Exactly(A), (), noop) of SubA
                                 (Exactly(A), (), noop) of SubA => (,)
                               }""").strip(), subgraph)

  def test_select_dependencies_with_separate_types_for_subselectors(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, C, field_types=(D,)),), noop),
      (B, (Select(D),), noop),
      (C, (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                                      {
                                        root_subject_types: (SubA,)
                                        root_rules: (Exactly(A), (SelectDependencies(B, C, u'dependencies', field_types=(D,)),), noop) of SubA
                                        (B, (Select(D),), noop) of D => (SubjectIsProduct(D),)
                                        (C, (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                                        (Exactly(A), (SelectDependencies(B, C, u'dependencies', field_types=(D,)),), noop) of SubA => ((C, (Select(SubA),), noop) of SubA, (B, (Select(D),), noop) of D,)
                                      }""").strip(),
                                    subgraph)

  def test_select_dependencies_with_subject_as_first_subselector(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(D,)),), noop),
      (B, (Select(D),), noop),
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                                      {
                                        root_subject_types: (SubA,)
                                        root_rules: (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(D,)),), noop) of SubA
                                        (B, (Select(D),), noop) of D => (SubjectIsProduct(D),)
                                        (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(D,)),), noop) of SubA => (SubjectIsProduct(SubA), (B, (Select(D),), noop) of D,)
                                      }""").strip(),
                                    subgraph)

  def test_select_dependencies_multiple_field_types_all_resolvable(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop),
      (B, (Select(Exactly(C, D)),), noop),
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                                      {
                                        root_subject_types: (SubA,)
                                        root_rules: (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C, D,)),), noop) of SubA
                                        (B, (Select(Exactly(C, D)),), noop) of C => (SubjectIsProduct(C),)
                                        (B, (Select(Exactly(C, D)),), noop) of D => (SubjectIsProduct(D),)
                                        (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C, D,)),), noop) of SubA => (SubjectIsProduct(SubA), (B, (Select(Exactly(C, D)),), noop) of C, (B, (Select(Exactly(C, D)),), noop) of D,)
                                      }""").strip(),
                                    subgraph)

  def test_select_dependencies_multiple_field_types_all_resolvable_with_deps(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop),
      # for the C type, it'll just be a literal, but for D, it'll traverse one more edge
      (B, (Select(C),), noop),
      (C, (Select(D),), noop),
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                                      {
                                        root_subject_types: (SubA,)
                                        root_rules: (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C, D,)),), noop) of SubA
                                        (B, (Select(C),), noop) of C => (SubjectIsProduct(C),)
                                        (B, (Select(C),), noop) of D => ((C, (Select(D),), noop) of D,)
                                        (C, (Select(D),), noop) of D => (SubjectIsProduct(D),)
                                        (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C, D,)),), noop) of SubA => (SubjectIsProduct(SubA), (B, (Select(C),), noop) of C, (B, (Select(C),), noop) of D,)
                                      }""").strip(),
                                    subgraph)

  def test_select_dependencies_recurse_with_different_type(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop),
      (B, (Select(A),), noop),
      (C, (Select(SubA),), noop),
      (SubA, tuple(), noop)
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                                      {
                                        root_subject_types: (SubA,)
                                        root_rules: (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C, D,)),), noop) of SubA
                                        (B, (Select(A),), noop) of C => ((Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C, D,)),), noop) of C,)
                                        (B, (Select(A),), noop) of D => ((Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C, D,)),), noop) of D,)
                                        (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C, D,)),), noop) of C => ((SubA, (), noop) of C, (B, (Select(A),), noop) of C, (B, (Select(A),), noop) of D,)
                                        (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C, D,)),), noop) of D => ((SubA, (), noop) of D, (B, (Select(A),), noop) of C, (B, (Select(A),), noop) of D,)
                                        (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C, D,)),), noop) of SubA => (SubjectIsProduct(SubA), (B, (Select(A),), noop) of C, (B, (Select(A),), noop) of D,)
                                        (SubA, (), noop) of C => (,)
                                        (SubA, (), noop) of D => (,)
                                      }""").strip(),
                                    subgraph)

  def test_select_dependencies_non_matching_subselector_because_of_intrinsic(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(D,)),), noop),
    ]
    intrinsics = [
      (C, B, noop),
    ]
    graphmaker = GraphMaker(RuleIndex.create(rules, intrinsics),
                            root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing('{empty graph}', subgraph)
    self.assert_equal_with_printing(dedent("""
                         Rules with errors: 1
                           (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(D,)),), noop):
                             no matches for Select(B) when resolving SelectDependencies(B, SubA, u'dependencies', field_types=(D,)) with subject types: D""").strip(),
                                    subgraph.error_message())

  def test_select_dependencies_with_matching_intrinsic(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C,)),), noop),
    ]
    intrinsics = [
      (B, C, noop),
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, intrinsics),
                            root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                                      {
                                        root_subject_types: (SubA,)
                                        root_rules: (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C,)),), noop) of SubA
                                        (Exactly(A), (SelectDependencies(B, SubA, u'dependencies', field_types=(C,)),), noop) of SubA => (SubjectIsProduct(SubA), IntrinsicRule(noop) of C,)
                                        IntrinsicRule(noop) of C => (,)
                                      }""").strip(),
                                    subgraph)

  def test_depends_on_multiple_one_noop(self):
    rules = [
      (B, (Select(A),), noop),
      (A, (Select(C),), noop),
      (A, (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=B)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: (B, (Select(A),), noop) of SubA
                                 (A, (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                                 (B, (Select(A),), noop) of SubA => ((A, (Select(SubA),), noop) of SubA,)
                               }""").strip(), subgraph)

  def test_multiple_depend_on_same_rule(self):
    rules = [
      (B, (Select(A),), noop),
      (C, (Select(A),), noop),
      (A, (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.full_graph()

    self.assert_equal_with_printing(dedent("""
                                      {
                                        root_subject_types: (SubA,)
                                        root_rules: (A, (Select(SubA),), noop) of SubA, (B, (Select(A),), noop) of SubA, (C, (Select(A),), noop) of SubA
                                        (A, (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                                        (B, (Select(A),), noop) of SubA => ((A, (Select(SubA),), noop) of SubA,)
                                        (C, (Select(A),), noop) of SubA => ((A, (Select(SubA),), noop) of SubA,)
                                      }""").strip(), subgraph)

  def test_select_literal(self):
    literally_a = A()
    rules = [
      (B, (SelectLiteral(literally_a, A),), noop)
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=B)

    self.assert_equal_with_printing(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: (B, (SelectLiteral(A(), A),), noop) of SubA
                                 (B, (SelectLiteral(A(), A),), noop) of SubA => (Literal(A(), A),)
                               }""").strip(), subgraph)

  def test_select_projection_simple(self):
    rules = [
      (Exactly(A), (SelectProjection(B, D, ('some',), SubA),), noop),
      (B, (Select(D),), noop),
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=A)

    self.assert_equal_with_printing(dedent("""
                                      {
                                        root_subject_types: (SubA,)
                                        root_rules: (Exactly(A), (SelectProjection(B, D, (u'some',), SubA),), noop) of SubA
                                        (B, (Select(D),), noop) of D => (SubjectIsProduct(D),)
                                        (Exactly(A), (SelectProjection(B, D, (u'some',), SubA),), noop) of SubA => (SubjectIsProduct(SubA), (B, (Select(D),), noop) of D,)
                                      }""").strip(),
                                    subgraph)

  def test_successful_when_one_field_type_is_unfulfillable(self):
    # NB We may want this to be a warning, since it may not be intentional
    rules = [
      (B, (Select(SubA),), noop),
      (D, (Select(Exactly(B)), SelectDependencies(B, SubA, field_types=(SubA, C))), noop)
    ]

    graphmaker = GraphMaker(RuleIndex.create(rules, tuple()),
      root_subject_fns=_suba_root_subject_fns)
    subgraph = graphmaker.generate_subgraph(SubA(), requested_product=D)

    self.assert_equal_with_printing(dedent("""
                                      {
                                        root_subject_types: (SubA,)
                                        root_rules: (D, (Select(Exactly(B)), SelectDependencies(B, SubA, u'dependencies', field_types=(SubA, C,))), noop) of SubA
                                        (B, (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                                        (D, (Select(Exactly(B)), SelectDependencies(B, SubA, u'dependencies', field_types=(SubA, C,))), noop) of SubA => ((B, (Select(SubA),), noop) of SubA, SubjectIsProduct(SubA), (B, (Select(SubA),), noop) of SubA,)
                                      }""").strip(),
      subgraph)

  assert_equal_with_printing = assert_equal_with_printing
