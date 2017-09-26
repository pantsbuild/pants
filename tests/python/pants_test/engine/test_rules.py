# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from textwrap import dedent

from pants.engine.addressable import Exactly
from pants.engine.build_files import create_graph_rules
from pants.engine.fs import create_fs_rules
from pants.engine.mapper import AddressMapper
from pants.engine.rules import RootRule, RuleIndex, SingletonRule, TaskRule
from pants.engine.scheduler import WrappedNativeScheduler
from pants.engine.selectors import Select, SelectDependencies, SelectProjection, SelectTransitive
from pants_test.engine.examples.parsers import JsonParser
from pants_test.engine.examples.planners import Goal
from pants_test.engine.util import (TargetTable, assert_equal_with_printing,
                                    create_native_scheduler, init_native)


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


_suba_root_rules = [RootRule(SubA)]


class RuleIndexTest(unittest.TestCase):
  def test_creation_fails_with_bad_declaration_type(self):
    with self.assertRaises(TypeError) as cm:
      RuleIndex.create([A()])
    self.assertEquals("Unexpected rule type: <class 'pants_test.engine.test_rules.A'>."
                      " Rules either extend Rule, or are static functions decorated with @rule.",
      str(cm.exception))


class RulesetValidatorTest(unittest.TestCase):
  def create_validator(self, goal_to_product, rules):
    return create_native_scheduler(rules)

  def test_ruleset_with_missing_product_type(self):
    rules = _suba_root_rules + [TaskRule(A, [Select(B)], noop)]
    scheduler = create_native_scheduler(rules)

    with self.assertRaises(ValueError) as cm:
      scheduler.assert_ruleset_valid()

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, (Select(B),), noop):
                         no matches for Select(B) with subject types: SubA
                     """).strip(),
                                    str(cm.exception))

  def test_ruleset_with_rule_with_two_missing_selects(self):
    rules = _suba_root_rules + [TaskRule(A, [Select(B), Select(C)], noop)]
    validator = self.create_validator({}, rules)
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
    rules = [RootRule(B), TaskRule(A, [Select(B)], noop)]
    validator = self.create_validator({}, rules)

    validator.assert_ruleset_valid()

  def test_ruleset_with_superclass_of_selected_type_produced_fails(self):
    rules = [
      RootRule(C),
      TaskRule(A, [Select(B)], noop),
      TaskRule(B, [Select(SubA)], noop)
    ]
    validator = self.create_validator({}, rules)

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
    rules = _suba_root_rules + [
      TaskRule(B, [Select(SubA)], noop)
    ]

    validator = self.create_validator({'goal-name': AGoal}, rules)
    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()

    self.assert_equal_with_printing("no task for product used by goal \"goal-name\": AGoal",
                                    str(cm.exception))

  def test_ruleset_with_explicit_type_constraint(self):
    rules = _suba_root_rules + [
      TaskRule(Exactly(A), [Select(B)], noop),
      TaskRule(B, [Select(A)], noop)
    ]
    validator = self.create_validator({}, rules)

    validator.assert_ruleset_valid()

  def test_ruleset_with_failure_due_to_incompatible_subject_for_singleton(self):
    rules = [
      RootRule(A),
      TaskRule(D, [Select(C)], noop),
      SingletonRule(B, B()),
    ]
    validator = self.create_validator({}, rules)

    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()

    # This error message could note near matches like the singleton.
    self.assert_equal_with_printing(dedent("""
                                      Rules with errors: 1
                                        (D, (Select(C),), noop):
                                          no matches for Select(C) with subject types: A
                                      """).strip(),
                                    str(cm.exception))

  def test_ruleset_unreachable_due_to_product_of_select_dependencies(self):
    rules = [
      RootRule(A),
      TaskRule(A, [SelectDependencies(B, SubA, field_types=(D,))], noop),
    ]
    validator = self.create_validator({}, rules)

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
    rules = _suba_root_rules + [
      TaskRule(B, [Select(D)], noop),
      TaskRule(D, [Select(A), SelectDependencies(A, SubA, field_types=(C,))], noop),
      TaskRule(A, [Select(SubA)], noop)
    ]
    validator = self.create_validator({}, rules)

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
    rules = _suba_root_rules + [
      TaskRule(Exactly(A), [SelectProjection(B, D, 'some', C)], noop),
    ]
    validator = self.create_validator({}, rules)

    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()

    self.assert_equal_with_printing(dedent("""
                      Rules with errors: 1
                        (A, (SelectProjection(B, D, 'some', C),), noop):
                          no matches for Select(C) when resolving SelectProjection(B, D, 'some', C) with subject types: SubA
                      """).strip(),
                                    str(cm.exception))

  def test_secondary_select_projection_failure(self):
    rules = _suba_root_rules + [
      TaskRule(Exactly(A), [SelectProjection(B, D, 'some', C)], noop),
      TaskRule(C, [], noop)
    ]

    validator = self.create_validator({}, rules)

    with self.assertRaises(ValueError) as cm:
      validator.assert_ruleset_valid()

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, (SelectProjection(B, D, 'some', C),), noop):
                         no matches for Select(B) when resolving SelectProjection(B, D, 'some', C) with subject types: D
                     """).strip(),
                                    str(cm.exception))

  assert_equal_with_printing = assert_equal_with_printing
# TODO should it raise if a particular root type can't get to a particular rule? Leaning towards
# no because it may be that there are some subgraphs particular to a particular root subject.


class RuleGraphMakerTest(unittest.TestCase):
  # TODO something with variants
  # TODO HasProducts?

  def test_smallest_full_test(self):
    rules = _suba_root_rules + [
      RootRule(SubA),
      TaskRule(Exactly(A), [Select(SubA)], noop)
    ]
    fullgraph = self.create_full_graph(RuleIndex.create(rules))

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
    symbol_table = TargetTable()
    address_mapper = AddressMapper(JsonParser(symbol_table), '*.BUILD.json')
    rules = create_graph_rules(address_mapper, symbol_table) + create_fs_rules()

    rule_index = RuleIndex.create(rules)
    fullgraph_str = self.create_full_graph(rule_index)

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

    self.assertEquals(36, len(all_rules))
    self.assertEquals(66, len(root_rule_lines)) # 2 lines per entry

  def test_smallest_full_test_multiple_root_subject_types(self):
    rules = [
      RootRule(SubA),
      RootRule(A),
      TaskRule(A, [Select(SubA)], noop),
      TaskRule(B, [Select(A)], noop)
    ]
    fullgraph = self.create_full_graph(RuleIndex.create(rules))

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
      TaskRule(Exactly(A), [Select(SubA)], noop)
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
      TaskRule(Exactly(A), [Select(SubA), Select(B)], noop),
      TaskRule(B, [], noop)
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
      TaskRule(Exactly(A), [Select(B)], noop),
      TaskRule(B, [Select(SubA)], noop)
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
      TaskRule(Exactly(A), [Select(C)], noop),
      TaskRule(Exactly(A), [], noop),
      SingletonRule(B, B()),
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

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
    rules = _suba_root_rules + [
      TaskRule(Exactly(A), [Select(C)], noop),
      TaskRule(Exactly(A), [], noop),
    ]

    fullgraph = self.create_full_graph(RuleIndex.create(rules))

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
    rules = [
      RootRule(C),
      RootRule(D),
      TaskRule(Exactly(A), [Select(C)], noop),
      TaskRule(Exactly(B), [Select(D), Select(A)], noop),
    ]

    fullgraph = self.create_full_graph(RuleIndex.create(rules))

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
      TaskRule(Exactly(B), [Select(C)], noop),
      TaskRule(Exactly(A), [Select(B)], noop),
      TaskRule(Exactly(A), [], noop),
    ]
    subgraph = self.create_subgraph(A, rules, SubA())

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

  def test_select_transitive_with_separate_types_for_subselectors(self):
    rules = [
      TaskRule(Exactly(A), [SelectTransitive(B, C, field_types=(D,))], noop),
      TaskRule(B, [Select(D)], noop),
      TaskRule(C, [Select(SubA)], noop)
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (SelectTransitive(B, C, field_types=(D,)),), noop) of SubA"}
                       // internal entries
                         "(A, (SelectTransitive(B, C, field_types=(D,)),), noop) of SubA" -> {"(C, (Select(SubA),), noop) of SubA" "(B, (Select(D),), noop) of D"}
                         "(B, (Select(D),), noop) of D" -> {"SubjectIsProduct(D)"}
                         "(C, (Select(SubA),), noop) of SubA" -> {"SubjectIsProduct(SubA)"}
                     }""").strip(),
      subgraph)

  def test_select_dependencies_with_separate_types_for_subselectors(self):
    rules = [
      TaskRule(Exactly(A), [SelectDependencies(B, C, field_types=(D,))], noop),
      TaskRule(B, [Select(D)], noop),
      TaskRule(C, [Select(SubA)], noop)
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
      TaskRule(Exactly(A), [SelectDependencies(B, SubA, field_types=(D,))], noop),
      TaskRule(B, [Select(D)], noop),
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
      TaskRule(Exactly(A), [SelectDependencies(B, SubA, field_types=(C, D,))], noop),
      TaskRule(B, [Select(Exactly(C, D))], noop),
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
      TaskRule(Exactly(A), [SelectDependencies(B, SubA, field_types=(C, D,))], noop),
      # for the C type, it'll just be a literal, but for D, it'll traverse one more edge
      TaskRule(B, [Select(C)], noop),
      TaskRule(C, [Select(D)], noop),
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
      TaskRule(Exactly(A), [SelectDependencies(B, SubA, field_types=(C, D,))], noop),
      TaskRule(B, [Select(A)], noop),
      TaskRule(C, [Select(SubA)], noop),
      TaskRule(SubA, [], noop)
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

  def test_select_dependencies_non_matching_subselector_because_of_singleton(self):
    rules = [
      TaskRule(Exactly(A), [SelectDependencies(B, SubA, field_types=(D,))], noop),
      SingletonRule(C, C()),
    ]
    subgraph = self.create_subgraph(A, rules, SubA())

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

  def test_select_dependencies_with_matching_singleton(self):
    rules = [
      TaskRule(Exactly(A), [SelectDependencies(B, SubA, field_types=(C,))], noop),
      SingletonRule(B, B()),
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    #TODO perhaps singletons should be marked in the dot format somehow
    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (SelectDependencies(B, SubA, field_types=(C,)),), noop) of SubA"}
                       // internal entries
                         "(A, (SelectDependencies(B, SubA, field_types=(C,)),), noop) of SubA" -> {"SubjectIsProduct(SubA)" "Singleton(B(), B)"}
                     }""").strip(),
      subgraph)

  def test_depends_on_multiple_one_noop(self):
    rules = [
      TaskRule(B, [Select(A)], noop),
      TaskRule(A, [Select(C)], noop),
      TaskRule(A, [Select(SubA)], noop)
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
    rules = _suba_root_rules + [
      TaskRule(B, [Select(A)], noop),
      TaskRule(C, [Select(A)], noop),
      TaskRule(A, [Select(SubA)], noop)
    ]

    subgraph = self.create_full_graph(RuleIndex.create(rules))

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

  def test_select_projection_simple(self):
    rules = [
      TaskRule(Exactly(A), [SelectProjection(B, D, 'some', SubA)], noop),
      TaskRule(B, [Select(D)], noop),
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, (SelectProjection(B, D, 'some', SubA),), noop) of SubA"}
                       // internal entries
                         "(A, (SelectProjection(B, D, 'some', SubA),), noop) of SubA" -> {"SubjectIsProduct(SubA)" "(B, (Select(D),), noop) of D"}
                         "(B, (Select(D),), noop) of D" -> {"SubjectIsProduct(D)"}
                     }""").strip(),
                                    subgraph)

  def test_successful_when_one_field_type_is_unfulfillable(self):
    # NB We may want this to be a warning, since it may not be intentional
    rules = [
      TaskRule(B, [Select(SubA)], noop),
      TaskRule(D, [Select(Exactly(B)), SelectDependencies(B, SubA, field_types=(SubA, C))], noop)
    ]

    subgraph = self.create_subgraph(D, rules, SubA())

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

  def create_scheduler(self, rule_index):
    native = init_native()
    scheduler = WrappedNativeScheduler(
      native=native,
      build_root='/tmp',
      work_dir='/tmp/.pants.d',
      ignore_patterns=tuple(),
      rule_index=rule_index)
    return scheduler

  def create_full_graph(self, rule_index):
    scheduler = self.create_scheduler(rule_index)

    return "\n".join(scheduler.rule_graph_visualization())

  def create_real_subgraph(self, rule_index, root_subject, product_type):
    scheduler = self.create_scheduler(rule_index)

    return "\n".join(scheduler.rule_subgraph_visualization(root_subject, product_type))

  def create_subgraph(self, requested_product, rules, subject):
    rules = rules + _suba_root_rules
    rule_index = RuleIndex.create(rules)
    return self.create_real_subgraph(rule_index, type(subject), requested_product)

  assert_equal_with_printing = assert_equal_with_printing
