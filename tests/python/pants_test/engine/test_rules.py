# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.base.specs import (AscendantAddresses, DescendantAddresses, SiblingAddresses,
                              SingleAddress)
from pants.build_graph.address import Address
from pants.engine.addressable import Exactly
from pants.engine.build_files import create_graph_tasks
from pants.engine.fs import PathGlobs, create_fs_tasks
from pants.engine.mapper import AddressMapper
from pants.engine.rules import Rule, RuleIndex
from pants.engine.scheduler import WrappedNativeScheduler
from pants.engine.selectors import Select, SelectDependencies, SelectLiteral, SelectProjection
from pants.engine.subsystem.native import Native
from pants_test.engine.examples.parsers import JsonParser
from pants_test.engine.examples.planners import Goal
from pants_test.engine.test_mapper import TargetTable
from pants_test.subsystem.subsystem_util import init_subsystem


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


_suba_root_subject_types = {SubA}


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
    a_intrinsic = (A, A, noop)
    with self.assertRaises(ValueError):
      RuleIndex.create([BoringRule(A)], (a_intrinsic, a_intrinsic))


class RulesetValidatorTest(unittest.TestCase):
  def create_validator(self, goal_to_product, intrinsic_entries, root_subject_types, rules):
    return self.create_native_scheduler(intrinsic_entries, root_subject_types, rules)

  def create_native_scheduler(self, intrinsic_entries, root_subject_types, rules):
    init_subsystem(Native.Factory)
    rule_index = RuleIndex.create(rules, intrinsic_entries)
    native = Native.Factory.global_instance().create()
    scheduler = WrappedNativeScheduler(native, '.', [], rule_index, root_subject_types)
    return scheduler

  def test_ruleset_with_missing_product_type(self):
    rules = [(A, (Select(B),), noop)]
    intrinsic_entries = tuple()
    root_subject_types = {SubA}
    scheduler = self.create_native_scheduler(intrinsic_entries, root_subject_types, rules)

    with self.assertRaises(ValueError) as cm:
      scheduler.assert_ruleset_valid()

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, (Select(B),), noop):
                         no matches for Select(B) with subject types: SubA
                     """).strip(),
                                    str(cm.exception))

  def test_ruleset_with_rule_with_two_missing_selects(self):
    rules = [(A, (Select(B), Select(C)), noop)]
    validator = self.create_validator({}, tuple(), {SubA}, rules)
    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, (Select(B), Select(C)), noop):
                         no matches for Select(B) with subject types: SubA
                         no matches for Select(C) with subject types: SubA
                     """).strip(),
      str(cm.exception))

  def test_ruleset_with_selector_only_provided_as_root_subject(self):
    rules = [(A, (Select(B),), noop)]
    validator = self.create_validator({}, tuple(), {B}, rules)

    validator.assert_ruleset_valid()

  def test_ruleset_with_superclass_of_selected_type_produced_fails(self):
    rules = [
      (A, (Select(B),), noop),
      (B, (Select(SubA),), noop)
    ]
    validator = self.create_validator({}, tuple(), {C}, rules)

    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()
    self.assert_equal_with_printing(dedent("""
                                      Rules with errors: 2
                                        (A, (Select(B),), noop):
                                          depends on unfulfillable (B, (Select(SubA),), noop) of C with subject types: C
                                        (B, (Select(SubA),), noop):
                                          no matches for Select(SubA) with subject types: C
                                      """).strip(),
                                    str(cm.exception))

  @unittest.skip('testing api not used by non-example code')
  def test_ruleset_with_goal_not_produced(self):
    # The graph is complete, but the goal 'goal-name' requests A,
    # which is not produced by any rule.
    rules = [
      (B, (Select(SubA),), noop)
    ]

    validator = self.create_validator({'goal-name': AGoal}, tuple(), {SubA}, rules)
    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()

    self.assert_equal_with_printing("no task for product used by goal \"goal-name\": AGoal",
                                    str(cm.exception))

  def test_ruleset_with_explicit_type_constraint(self):
    rules = [
      (Exactly(A), (Select(B),), noop),
      (B, (Select(A),), noop)
    ]
    validator = self.create_validator({}, tuple(), {SubA}, rules)

    validator.assert_ruleset_valid()

  def test_ruleset_with_failure_due_to_incompatible_subject_for_intrinsic(self):
    rules = [
      (D, (Select(C),), noop)
    ]
    intrinsics = [
      (B, C, noop),
    ]
    validator = self.create_validator({}, intrinsics, {A}, rules)

    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()

    # This error message could note near matches like the intrinsic.
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
    validator = self.create_validator({}, intrinsics, {A}, rules)

    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()

    self.assert_equal_with_printing(dedent("""
                             Rules with errors: 1
                               (A, (SelectDependencies(B, SubA, field_types=(D,)),), noop):
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
    validator = self.create_validator({}, tuple(), _suba_root_subject_types, rules)

    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()

    self.assert_equal_with_printing(dedent("""
                      Rules with errors: 2
                        (B, (Select(D),), noop):
                          depends on unfulfillable (D, (Select(A), SelectDependencies(A, SubA, field_types=(C,))), noop) of SubA with subject types: SubA
                        (D, (Select(A), SelectDependencies(A, SubA, field_types=(C,))), noop):
                          depends on unfulfillable (A, (Select(SubA),), noop) of C with subject types: SubA
                      """).strip(),
        str(cm.exception))

  def test_initial_select_projection_failure(self):
    rules = [
      (Exactly(A), (SelectProjection(B, D, ('some',), C),), noop),
    ]
    validator = self.create_validator({}, tuple(), _suba_root_subject_types, rules)

    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()

    self.assert_equal_with_printing(dedent("""
                      Rules with errors: 1
                        (A, (SelectProjection(B, D, ('some',), C),), noop):
                          no matches for Select(C) when resolving SelectProjection(B, D, ('some',), C) with subject types: SubA
                      """).strip(),
                                    str(cm.exception))

  def test_secondary_select_projection_failure(self):
    rules = [
      (Exactly(A), (SelectProjection(B, D, ('some',), C),), noop),
      (C, tuple(), noop)
    ]

    validator = self.create_validator({}, tuple(), _suba_root_subject_types, rules)

    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, (SelectProjection(B, D, ('some',), C),), noop):
                         no matches for Select(B) when resolving SelectProjection(B, D, ('some',), C) with subject types: D
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
    fullgraph = self.create_full_graph({SubA}, RuleIndex.create(rules, tuple()))

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (Select(SubA),), noop) of SubA"}
                       // internal entries
                         "(A, (Select(SubA),), noop) of SubA" -> {"SubjectIsProduct(SubA)"}
                     }""").strip(), fullgraph)

  def test_full_graph_for_planner_example(self):
    symbol_table_cls = TargetTable
    address_mapper = AddressMapper(symbol_table_cls, JsonParser, '*.BUILD.json')
    project_tree = 'Let us pretend that this is a ProjectTree!'
    tasks = create_graph_tasks(address_mapper, symbol_table_cls) + create_fs_tasks(project_tree)

    rule_index = RuleIndex.create(tasks, tuple())
    root_subject_types = {Address,
                          PathGlobs,
                          SingleAddress,
                          SiblingAddresses,
                          DescendantAddresses,
                          AscendantAddresses}
    fullgraph_str = self.create_full_graph(root_subject_types, rule_index)

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

    self.assertEquals(31, len(all_rules))
    self.assertEquals(56, len(root_rule_lines)) # 2 lines per entry

  def test_smallest_full_test_multiple_root_subject_types(self):
    rules = [
      (A, (Select(SubA),), noop),
      (B, (Select(A),), noop)
    ]
    fullgraph = self.create_full_graph(OrderedSet([SubA, A]), RuleIndex.create(rules, tuple()))

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: A, SubA
                       // root entries
                         "Select(A) for A" [color=blue]
                         "Select(A) for A" -> {"SubjectIsProduct(A)"}
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (Select(SubA),), noop) of SubA"}
                         "Select(B) for A" [color=blue]
                         "Select(B) for A" -> {"(B, (Select(A),), noop) of A"}
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, (Select(A),), noop) of SubA"}
                       // internal entries
                         "(A, (Select(SubA),), noop) of SubA" -> {"SubjectIsProduct(SubA)"}
                         "(B, (Select(A),), noop) of A" -> {"SubjectIsProduct(A)"}
                         "(B, (Select(A),), noop) of SubA" -> {"(A, (Select(SubA),), noop) of SubA"}
                     }""").strip(),
                     fullgraph)

  def test_single_rule_depending_on_subject_selection(self):
    rules = [
      (Exactly(A), (Select(SubA),), noop)
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (Select(SubA),), noop) of SubA"}
                       // internal entries
                         "(A, (Select(SubA),), noop) of SubA" -> {"SubjectIsProduct(SubA)"}
                     }""").strip(),
      subgraph)

  def test_multiple_selects(self):
    rules = [
      (Exactly(A), (Select(SubA), Select(B)), noop),
      (B, tuple(), noop)
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (Select(SubA), Select(B)), noop) of SubA"}
                       // internal entries
                         "(A, (Select(SubA), Select(B)), noop) of SubA" -> {"SubjectIsProduct(SubA)" "(B, (,), noop) of SubA"}
                         "(B, (,), noop) of SubA" -> {}
                     }""").strip(),
      subgraph)

  def test_one_level_of_recursion(self):
    rules = [
      (Exactly(A), (Select(B),), noop),
      (B, (Select(SubA),), noop)
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (Select(B),), noop) of SubA"}
                       // internal entries
                         "(A, (Select(B),), noop) of SubA" -> {"(B, (Select(SubA),), noop) of SubA"}
                         "(B, (Select(SubA),), noop) of SubA" -> {"SubjectIsProduct(SubA)"}
                     }""").strip(),
      subgraph)

  def test_noop_removal_in_subgraph(self):
    rules = [
      # C is provided by an intrinsic, but only if the subject is B.
      (Exactly(A), (Select(C),), noop),
      (Exactly(A), tuple(), noop),
    ]
    intrinsics = [
      (B, C, noop),
    ]

    subgraph = self.create_subgraph_with_intrinsics(intrinsics,
                                                    A,
                                                    rules,
                                                    SubA(),
                                                    _suba_root_subject_types)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (,), noop) of SubA"}
                       // internal entries
                         "(A, (,), noop) of SubA" -> {}
                     }""").strip(),
      subgraph)

  def test_noop_removal_full_single_subject_type(self):
    rules = [
      # C is provided by an intrinsic, but only if the subject is B.
      (Exactly(A), (Select(C),), noop),
      (Exactly(A), tuple(), noop),
    ]
    intrinsics = [
      (B, C, noop),
    ]

    fullgraph = self.create_full_graph(_suba_root_subject_types,
                                       RuleIndex.create(rules, intrinsics))

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (,), noop) of SubA"}
                       // internal entries
                         "(A, (,), noop) of SubA" -> {}
                     }""").strip(),
      fullgraph)

  def test_root_tuple_removed_when_no_matches(self):
    root_subjects = {C, D}
    rules = [
      (Exactly(A), (Select(C),), noop),
      (Exactly(B), (Select(D), Select(A)), noop),
    ]
    intrinsics = []

    fullgraph = self.create_full_graph(root_subjects,
                                       RuleIndex.create(rules, intrinsics))

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: C, D
                       // root entries
                         "Select(A) for C" [color=blue]
                         "Select(A) for C" -> {"(A, (Select(C),), noop) of C"}
                       // internal entries
                         "(A, (Select(C),), noop) of C" -> {"SubjectIsProduct(C)"}
                     }""").strip(),
      fullgraph)

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
    subgraph = self.create_subgraph_with_intrinsics(intrinsics,
                                                    A,
                                                    rules,
                                                    SubA(),
                                                    _suba_root_subject_types)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (,), noop) of SubA"}
                       // internal entries
                         "(A, (,), noop) of SubA" -> {}
                     }""").strip(),
      subgraph)

  def test_select_dependencies_with_separate_types_for_subselectors(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, C, field_types=(D,)),), noop),
      (B, (Select(D),), noop),
      (C, (Select(SubA),), noop)
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (SelectDependencies(B, C, field_types=(D,)),), noop) of SubA"}
                       // internal entries
                         "(A, (SelectDependencies(B, C, field_types=(D,)),), noop) of SubA" -> {"(C, (Select(SubA),), noop) of SubA" "(B, (Select(D),), noop) of D"}
                         "(B, (Select(D),), noop) of D" -> {"SubjectIsProduct(D)"}
                         "(C, (Select(SubA),), noop) of SubA" -> {"SubjectIsProduct(SubA)"}
                     }""").strip(),
      subgraph)

  def test_select_dependencies_with_subject_as_first_subselector(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(D,)),), noop),
      (B, (Select(D),), noop),
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (SelectDependencies(B, SubA, field_types=(D,)),), noop) of SubA"}
                       // internal entries
                         "(A, (SelectDependencies(B, SubA, field_types=(D,)),), noop) of SubA" -> {"SubjectIsProduct(SubA)" "(B, (Select(D),), noop) of D"}
                         "(B, (Select(D),), noop) of D" -> {"SubjectIsProduct(D)"}
                     }""").strip(),
      subgraph)

  def test_select_dependencies_multiple_field_types_all_resolvable(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop),
      (B, (Select(Exactly(C, D)),), noop),
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA"}
                       // internal entries
                         "(A, (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA" -> {"SubjectIsProduct(SubA)" "(B, (Select(Exactly(C, D)),), noop) of C" "(B, (Select(Exactly(C, D)),), noop) of D"}
                         "(B, (Select(Exactly(C, D)),), noop) of C" -> {"SubjectIsProduct(C)"}
                         "(B, (Select(Exactly(C, D)),), noop) of D" -> {"SubjectIsProduct(D)"}
                     }""").strip(),
      subgraph)

  def test_select_dependencies_multiple_field_types_all_resolvable_with_deps(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop),
      # for the C type, it'll just be a literal, but for D, it'll traverse one more edge
      (B, (Select(C),), noop),
      (C, (Select(D),), noop),
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA"}
                       // internal entries
                         "(A, (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA" -> {"SubjectIsProduct(SubA)" "(B, (Select(C),), noop) of C" "(B, (Select(C),), noop) of D"}
                         "(B, (Select(C),), noop) of C" -> {"SubjectIsProduct(C)"}
                         "(B, (Select(C),), noop) of D" -> {"(C, (Select(D),), noop) of D"}
                         "(C, (Select(D),), noop) of D" -> {"SubjectIsProduct(D)"}
                     }""").strip(),
      subgraph)

  def test_select_dependencies_recurse_with_different_type(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop),
      (B, (Select(A),), noop),
      (C, (Select(SubA),), noop),
      (SubA, tuple(), noop)
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA"}
                       // internal entries
                         "(A, (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of C" -> {"(SubA, (,), noop) of C" "(B, (Select(A),), noop) of C" "(B, (Select(A),), noop) of D"}
                         "(A, (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of D" -> {"(SubA, (,), noop) of D" "(B, (Select(A),), noop) of C" "(B, (Select(A),), noop) of D"}
                         "(A, (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA" -> {"SubjectIsProduct(SubA)" "(B, (Select(A),), noop) of C" "(B, (Select(A),), noop) of D"}
                         "(B, (Select(A),), noop) of C" -> {"(A, (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of C"}
                         "(B, (Select(A),), noop) of D" -> {"(A, (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of D"}
                         "(SubA, (,), noop) of C" -> {}
                         "(SubA, (,), noop) of D" -> {}
                     }""").strip(),
      subgraph)

  def test_select_dependencies_non_matching_subselector_because_of_intrinsic(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(D,)),), noop),
    ]
    intrinsics = [
      (C, B, noop),
    ]
    subgraph = self.create_subgraph_with_intrinsics(intrinsics, A, rules, SubA(),
                                                    _suba_root_subject_types)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // empty graph
                     }""").strip(),
      subgraph)
    #self.assert_equal_with_printing(dedent("""
    #                     Rules with errors: 1
    #                       (Exactly(A), (SelectDependencies(B, SubA, field_types=(D,)),), noop):
    #                         no matches for Select(B) when resolving SelectDependencies(B, SubA, field_types=(D,)) with subject types: D""").strip(),
    #                                subgraph.error_message())

  def test_select_dependencies_with_matching_intrinsic(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C,)),), noop),
    ]
    intrinsics = [
      (B, C, noop),
    ]

    subgraph = self.create_subgraph_with_intrinsics(intrinsics, A, rules, SubA(),
                                                    _suba_root_subject_types)

    #TODO perhaps intrinsics should be marked in the dot format somehow
    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (SelectDependencies(B, SubA, field_types=(C,)),), noop) of SubA"}
                       // internal entries
                         "(A, (SelectDependencies(B, SubA, field_types=(C,)),), noop) of SubA" -> {"SubjectIsProduct(SubA)" "(B, (Select(C),), noop) of C"}
                         "(B, (Select(C),), noop) of C" -> {"SubjectIsProduct(C)"}
                     }""").strip(),
      subgraph)

  def test_depends_on_multiple_one_noop(self):
    rules = [
      (B, (Select(A),), noop),
      (A, (Select(C),), noop),
      (A, (Select(SubA),), noop)
    ]

    subgraph = self.create_subgraph(B, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, (Select(A),), noop) of SubA"}
                       // internal entries
                         "(A, (Select(SubA),), noop) of SubA" -> {"SubjectIsProduct(SubA)"}
                         "(B, (Select(A),), noop) of SubA" -> {"(A, (Select(SubA),), noop) of SubA"}
                     }""").strip(),
      subgraph)

  def test_multiple_depend_on_same_rule(self):
    rules = [
      (B, (Select(A),), noop),
      (C, (Select(A),), noop),
      (A, (Select(SubA),), noop)
    ]

    subgraph = self.create_full_graph(_suba_root_subject_types, RuleIndex.create(rules, tuple()))

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (Select(SubA),), noop) of SubA"}
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, (Select(A),), noop) of SubA"}
                         "Select(C) for SubA" [color=blue]
                         "Select(C) for SubA" -> {"(C, (Select(A),), noop) of SubA"}
                       // internal entries
                         "(A, (Select(SubA),), noop) of SubA" -> {"SubjectIsProduct(SubA)"}
                         "(B, (Select(A),), noop) of SubA" -> {"(A, (Select(SubA),), noop) of SubA"}
                         "(C, (Select(A),), noop) of SubA" -> {"(A, (Select(SubA),), noop) of SubA"}
                     }""").strip(),
      subgraph)

  def test_select_literal(self):
    literally_a = A()
    rules = [
      (B, (SelectLiteral(literally_a, A),), noop)
    ]

    subgraph = self.create_subgraph(B, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, (SelectLiteral(A(), A),), noop) of SubA"}
                       // internal entries
                         "(B, (SelectLiteral(A(), A),), noop) of SubA" -> {"Literal(A(), A)"}
                     }""").strip(),
      subgraph)

  def test_select_projection_simple(self):
    rules = [
      (Exactly(A), (SelectProjection(B, D, ('some',), SubA),), noop),
      (B, (Select(D),), noop),
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (SelectProjection(B, D, ('some',), SubA),), noop) of SubA"}
                       // internal entries
                         "(A, (SelectProjection(B, D, ('some',), SubA),), noop) of SubA" -> {"SubjectIsProduct(SubA)" "(B, (Select(D),), noop) of D"}
                         "(B, (Select(D),), noop) of D" -> {"SubjectIsProduct(D)"}
                     }""").strip(),
                                    subgraph)

  def test_successful_when_one_field_type_is_unfulfillable(self):
    # NB We may want this to be a warning, since it may not be intentional
    rules = [
      (B, (Select(SubA),), noop),
      (D, (Select(Exactly(B)), SelectDependencies(B, SubA, field_types=(SubA, C))), noop)
    ]

    subgraph = self.create_subgraph_with_intrinsics(tuple(), D, rules, SubA(),
                                                    _suba_root_subject_types)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(D) for SubA" [color=blue]
                         "Select(D) for SubA" -> {"(D, (Select(B), SelectDependencies(B, SubA, field_types=(SubA, C,))), noop) of SubA"}
                       // internal entries
                         "(B, (Select(SubA),), noop) of SubA" -> {"SubjectIsProduct(SubA)"}
                         "(D, (Select(B), SelectDependencies(B, SubA, field_types=(SubA, C,))), noop) of SubA" -> {"(B, (Select(SubA),), noop) of SubA" "SubjectIsProduct(SubA)"}
                     }""").strip(),
      subgraph)

  def create_scheduler(self, root_subject_types, rule_index):
    native = Native.Factory.global_instance().create()
    scheduler = WrappedNativeScheduler(
      native=native,
      build_root='/tmp',
      ignore_patterns=tuple(),
      rule_index=rule_index,
      root_subject_types=root_subject_types)
    return scheduler

  def create_full_graph(self, root_subject_types, rule_index):
    scheduler = self.create_scheduler(root_subject_types, rule_index)

    return "\n".join(scheduler.rule_graph_visualization())

  def create_real_subgraph(self, root_subject_types, rule_index, root_subject, product_type):
    scheduler = self.create_scheduler(root_subject_types, rule_index)

    return "\n".join(scheduler.rule_subgraph_visualization(root_subject, product_type))

  def create_subgraph(self, requested_product, rules, subject):
    subgraph = self.create_subgraph_with_intrinsics(tuple(), requested_product, rules, subject,
                                                    _suba_root_subject_types)
    return subgraph

  def create_subgraph_with_intrinsics(self, intrinsics, requested_product, rules, subject,
                                        subject_types):
    rule_index = RuleIndex.create(rules, intrinsics)

    return self.create_real_subgraph(subject_types, rule_index, type(subject), requested_product)

  assert_equal_with_printing = assert_equal_with_printing
