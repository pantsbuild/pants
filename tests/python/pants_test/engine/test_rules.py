# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import unittest
from builtins import object, str
from textwrap import dedent

from pants.engine.build_files import create_graph_rules
from pants.engine.console import Console
from pants.engine.fs import create_fs_rules
from pants.engine.mapper import AddressMapper
from pants.engine.rules import (RootRule, RuleIndex, SingletonRule, TaskRule, _GoalProduct,
                                console_rule)
from pants.engine.selectors import Get, Select
from pants.util.objects import Exactly
from pants_test.engine.examples.parsers import JsonParser
from pants_test.engine.util import (TargetTable, assert_equal_with_printing, create_scheduler,
                                    run_rule)


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


@console_rule('example', [Select(Console)])
def a_console_rule_generator(console):
  a = yield Get(A, str('a str!'))
  console.print_stdout(str(a))


class RuleTest(unittest.TestCase):
  def test_run_rule_console_rule_generator(self):
    res = run_rule(a_console_rule_generator, Console(), {
        (A, str): lambda _: A(),
      })
    self.assertEquals(res, _GoalProduct.for_name('example')())


class RuleIndexTest(unittest.TestCase):
  def test_creation_fails_with_bad_declaration_type(self):
    with self.assertRaises(TypeError) as cm:
      RuleIndex.create([A()])
    self.assertEqual("Unexpected rule type: <class 'pants_test.engine.test_rules.A'>."
                      " Rules either extend Rule, or are static functions decorated with @rule.",
      str(cm.exception))


class RulesetValidatorTest(unittest.TestCase):
  def test_ruleset_with_missing_product_type(self):
    rules = _suba_root_rules + [TaskRule(A, [Select(B)], noop)]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, [Select(B)], noop):
                         No rule was available to compute B with parameter type SubA
                     """).strip(),
                                    str(cm.exception))

  def test_ruleset_with_ambiguity(self):
    rules = [
        TaskRule(A, [Select(C), Select(B)], noop),
        TaskRule(A, [Select(B), Select(C)], noop),
        RootRule(B),
        RootRule(C),
        # TODO: Without a rule triggering the selection of A, we don't detect ambiguity here.
        TaskRule(D, [Select(A)], noop),
      ]
    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (D, [Select(A)], noop):
                         ambiguous rules for Select(A) with parameter types (B+C):
                           (A, [Select(B), Select(C)], noop) for (B+C)
                           (A, [Select(C), Select(B)], noop) for (B+C)
                     """).strip(),
      str(cm.exception))

  def test_ruleset_with_rule_with_two_missing_selects(self):
    rules = _suba_root_rules + [TaskRule(A, [Select(B), Select(C)], noop)]
    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, [Select(B), Select(C)], noop):
                         No rule was available to compute B with parameter type SubA
                         No rule was available to compute C with parameter type SubA
                     """).strip(),
      str(cm.exception))

  def test_ruleset_with_selector_only_provided_as_root_subject(self):
    rules = [RootRule(B), TaskRule(A, [Select(B)], noop)]
    create_scheduler(rules)

  def test_ruleset_with_superclass_of_selected_type_produced_fails(self):
    rules = [
      RootRule(C),
      TaskRule(A, [Select(B)], noop),
      TaskRule(B, [Select(SubA)], noop)
    ]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)
    self.assert_equal_with_printing(dedent("""
                                      Rules with errors: 2
                                        (A, [Select(B)], noop):
                                          No rule was available to compute B with parameter type C
                                        (B, [Select(SubA)], noop):
                                          No rule was available to compute SubA with parameter type C
                                      """).strip(),
                                    str(cm.exception))

  def test_ruleset_with_explicit_type_constraint(self):
    rules = _suba_root_rules + [
      TaskRule(Exactly(A), [Select(B)], noop),
      TaskRule(B, [Select(A)], noop)
    ]
    create_scheduler(rules)

  def test_ruleset_with_failure_due_to_incompatible_subject_for_singleton(self):
    rules = [
      RootRule(A),
      TaskRule(D, [Select(C)], noop),
      SingletonRule(B, B()),
    ]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    # This error message could note near matches like the singleton.
    self.assert_equal_with_printing(dedent("""
                                      Rules with errors: 1
                                        (D, [Select(C)], noop):
                                          No rule was available to compute C with parameter type A
                                      """).strip(),
                                    str(cm.exception))

  def test_not_fulfillable_duplicated_dependency(self):
    # If a rule depends on another rule+subject in two ways, and one of them is unfulfillable
    # Only the unfulfillable one should be in the errors.
    rules = _suba_root_rules + [
      TaskRule(B, [Select(D)], noop),
      TaskRule(D, [Select(A), Select(SubA)], noop, input_gets=[Get(A, C)]),
      TaskRule(A, [Select(C)], noop)
    ]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(dedent("""
                      Rules with errors: 2
                        (B, [Select(D)], noop):
                          No rule was available to compute D with parameter type SubA
                        (D, [Select(A), Select(SubA)], [Get(A, C)], noop):
                          No rule was available to compute A with parameter type SubA
                      """).strip(),
        str(cm.exception))

  assert_equal_with_printing = assert_equal_with_printing


class RuleGraphMakerTest(unittest.TestCase):
  # TODO HasProducts?

  def test_smallest_full_test(self):
    rules = _suba_root_rules + [
      RootRule(SubA),
      TaskRule(Exactly(A), [Select(SubA)], noop)
    ]
    fullgraph = self.create_full_graph(rules)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, [Select(SubA)], noop) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], noop) for SubA" -> {"Param(SubA)"}
                     }""").strip(), fullgraph)

  def test_full_graph_for_planner_example(self):
    symbol_table = TargetTable()
    address_mapper = AddressMapper(JsonParser(symbol_table), '*.BUILD.json')
    rules = create_graph_rules(address_mapper, symbol_table) + create_fs_rules()

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
    rules = [
      RootRule(SubA),
      RootRule(A),
      TaskRule(A, [Select(SubA)], noop),
      TaskRule(B, [Select(A)], noop)
    ]
    fullgraph = self.create_full_graph(rules)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: A, SubA
                       // root entries
                         "Select(A) for A" [color=blue]
                         "Select(A) for A" -> {"Param(A)"}
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, [Select(SubA)], noop) for SubA"}
                         "Select(B) for A" [color=blue]
                         "Select(B) for A" -> {"(B, [Select(A)], noop) for A"}
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, [Select(A)], noop) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], noop) for SubA" -> {"Param(SubA)"}
                         "(B, [Select(A)], noop) for A" -> {"Param(A)"}
                         "(B, [Select(A)], noop) for SubA" -> {"(A, [Select(SubA)], noop) for SubA"}
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
                         "Select(A) for SubA" -> {"(A, [Select(SubA)], noop) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], noop) for SubA" -> {"Param(SubA)"}
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
                         "Select(A) for SubA" -> {"(A, [Select(SubA), Select(B)], noop) for SubA"}
                       // internal entries
                         "(A, [Select(SubA), Select(B)], noop) for SubA" -> {"(B, [], noop) for ()" "Param(SubA)"}
                         "(B, [], noop) for ()" -> {}
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
                         "Select(A) for SubA" -> {"(A, [Select(B)], noop) for SubA"}
                       // internal entries
                         "(A, [Select(B)], noop) for SubA" -> {"(B, [Select(SubA)], noop) for SubA"}
                         "(B, [Select(SubA)], noop) for SubA" -> {"Param(SubA)"}
                     }""").strip(),
      subgraph)

  def test_noop_removal_in_subgraph(self):
    rules = [
      TaskRule(Exactly(A), [Select(C)], noop),
      TaskRule(Exactly(A), [], noop),
      SingletonRule(B, B()),
    ]

    subgraph = self.create_subgraph(A, rules, SubA(), validate=False)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for ()" [color=blue]
                         "Select(A) for ()" -> {"(A, [], noop) for ()"}
                       // internal entries
                         "(A, [], noop) for ()" -> {}
                     }""").strip(),
      subgraph)

  def test_noop_removal_full_single_subject_type(self):
    rules = _suba_root_rules + [
      TaskRule(Exactly(A), [Select(C)], noop),
      TaskRule(Exactly(A), [], noop),
    ]

    fullgraph = self.create_full_graph(rules, validate=False)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for ()" [color=blue]
                         "Select(A) for ()" -> {"(A, [], noop) for ()"}
                       // internal entries
                         "(A, [], noop) for ()" -> {}
                     }""").strip(),
      fullgraph)

  def test_root_tuple_removed_when_no_matches(self):
    rules = [
      RootRule(C),
      RootRule(D),
      TaskRule(Exactly(A), [Select(C)], noop),
      TaskRule(Exactly(B), [Select(D), Select(A)], noop),
    ]

    fullgraph = self.create_full_graph(rules, validate=False)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: C, D
                       // root entries
                         "Select(A) for C" [color=blue]
                         "Select(A) for C" -> {"(A, [Select(C)], noop) for C"}
                         "Select(B) for (C+D)" [color=blue]
                         "Select(B) for (C+D)" -> {"(B, [Select(D), Select(A)], noop) for (C+D)"}
                       // internal entries
                         "(A, [Select(C)], noop) for C" -> {"Param(C)"}
                         "(B, [Select(D), Select(A)], noop) for (C+D)" -> {"(A, [Select(C)], noop) for C" "Param(D)"}
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
    subgraph = self.create_subgraph(A, rules, SubA(), validate=False)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for ()" [color=blue]
                         "Select(A) for ()" -> {"(A, [], noop) for ()"}
                       // internal entries
                         "(A, [], noop) for ()" -> {}
                     }""").strip(),
      subgraph)

  def test_get_with_matching_singleton(self):
    rules = [
      TaskRule(Exactly(A), [Select(SubA)], noop, input_gets=[Get(B, C)]),
      SingletonRule(B, B()),
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, [Select(SubA)], [Get(B, C)], noop) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], [Get(B, C)], noop) for SubA" -> {"Param(SubA)" "Singleton(B(), B)"}
                     }""").strip(),
      subgraph)

  def test_depends_on_multiple_one_noop(self):
    rules = [
      TaskRule(B, [Select(A)], noop),
      TaskRule(A, [Select(C)], noop),
      TaskRule(A, [Select(SubA)], noop)
    ]

    subgraph = self.create_subgraph(B, rules, SubA(), validate=False)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, [Select(A)], noop) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], noop) for SubA" -> {"Param(SubA)"}
                         "(B, [Select(A)], noop) for SubA" -> {"(A, [Select(SubA)], noop) for SubA"}
                     }""").strip(),
      subgraph)

  def test_multiple_depend_on_same_rule(self):
    rules = _suba_root_rules + [
      TaskRule(B, [Select(A)], noop),
      TaskRule(C, [Select(A)], noop),
      TaskRule(A, [Select(SubA)], noop)
    ]

    subgraph = self.create_full_graph(rules)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, [Select(SubA)], noop) for SubA"}
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, [Select(A)], noop) for SubA"}
                         "Select(C) for SubA" [color=blue]
                         "Select(C) for SubA" -> {"(C, [Select(A)], noop) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], noop) for SubA" -> {"Param(SubA)"}
                         "(B, [Select(A)], noop) for SubA" -> {"(A, [Select(SubA)], noop) for SubA"}
                         "(C, [Select(A)], noop) for SubA" -> {"(A, [Select(SubA)], noop) for SubA"}
                     }""").strip(),
      subgraph)

  def test_get_simple(self):
    rules = [
      TaskRule(Exactly(A), [], noop, [Get(B, D)]),
      TaskRule(B, [Select(D)], noop),
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for ()" [color=blue]
                         "Select(A) for ()" -> {"(A, [], [Get(B, D)], noop) for ()"}
                       // internal entries
                         "(A, [], [Get(B, D)], noop) for ()" -> {"(B, [Select(D)], noop) for D"}
                         "(B, [Select(D)], noop) for D" -> {"Param(D)"}
                     }""").strip(),
                                    subgraph)

  def create_full_graph(self, rules, validate=True):
    scheduler = create_scheduler(rules, validate=validate)
    return "\n".join(scheduler.rule_graph_visualization())

  def create_subgraph(self, requested_product, rules, subject, validate=True):
    scheduler = create_scheduler(rules + _suba_root_rules, validate=validate)
    return "\n".join(scheduler.rule_subgraph_visualization(type(subject), requested_product))

  assert_equal_with_printing = assert_equal_with_printing
