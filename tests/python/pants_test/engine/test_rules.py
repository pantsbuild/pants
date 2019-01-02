# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re
import sys
import unittest
from builtins import object, str
from textwrap import dedent

from pants.engine.build_files import create_graph_rules
from pants.engine.console import Console
from pants.engine.fs import create_fs_rules
from pants.engine.mapper import AddressMapper
from pants.engine.rules import (RootRule, RuleIndex, SingletonRule, _GoalProduct, _RuleVisitor,
                                console_rule, rule)
from pants.engine.selectors import Get, Select
from pants.util.objects import Exactly
from pants_test.engine.examples.parsers import JsonParser
from pants_test.engine.util import (TargetTable, assert_equal_with_printing, create_scheduler,
                                    run_rule)
from pants_test.testutils.py2_compat import assertRegex


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
    @rule(A, [Select(B)])
    def a_from_b_noop(b):
      pass

    rules = _suba_root_rules + [a_from_b_noop]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, [Select(B)], a_from_b_noop):
                         No rule was available to compute B with parameter type SubA
                     """).strip(),
                                    str(cm.exception))

  def test_ruleset_with_ambiguity(self):
    @rule(A, [Select(C), Select(B)])
    def a_from_c_and_b(c, b):
      pass

    @rule(A, [Select(B), Select(C)])
    def a_from_b_and_c(b, c):
      pass

    @rule(D, [Select(A)])
    def d_from_a(a):
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

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (D, [Select(A)], d_from_a):
                         ambiguous rules for Select(A) with parameter types (B+C):
                           (A, [Select(B), Select(C)], a_from_b_and_c) for (B+C)
                           (A, [Select(C), Select(B)], a_from_c_and_b) for (B+C)
                     """).strip(),
      str(cm.exception))

  def test_ruleset_with_rule_with_two_missing_selects(self):
    @rule(A, [Select(B), Select(C)])
    def a_from_b_and_c(b, c):
      pass

    rules = _suba_root_rules + [a_from_b_and_c]
    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, [Select(B), Select(C)], a_from_b_and_c):
                         No rule was available to compute B with parameter type SubA
                         No rule was available to compute C with parameter type SubA
                     """).strip(),
      str(cm.exception))

  def test_ruleset_with_selector_only_provided_as_root_subject(self):
    @rule(A, [Select(B)])
    def a_from_b(b):
      pass

    rules = [RootRule(B), a_from_b]
    create_scheduler(rules)

  def test_ruleset_with_superclass_of_selected_type_produced_fails(self):
    @rule(A, [Select(B)])
    def a_from_b(b):
      pass

    @rule(B, [Select(SubA)])
    def b_from_suba(suba):
      pass

    rules = [
      RootRule(C),
      a_from_b,
      b_from_suba,
    ]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)
    self.assert_equal_with_printing(dedent("""
                                      Rules with errors: 2
                                        (A, [Select(B)], a_from_b):
                                          No rule was available to compute B with parameter type C
                                        (B, [Select(SubA)], b_from_suba):
                                          No rule was available to compute SubA with parameter type C
                                      """).strip(),
                                    str(cm.exception))

  def test_ruleset_with_explicit_type_constraint(self):
    @rule(Exactly(A), [Select(B)])
    def a_from_b(b):
      pass

    @rule(B, [Select(A)])
    def b_from_a(a):
      pass

    rules = _suba_root_rules + [
      a_from_b,
      b_from_a,
    ]
    create_scheduler(rules)

  def test_ruleset_with_failure_due_to_incompatible_subject_for_singleton(self):
    @rule(D, [Select(C)])
    def d_from_c(c):
      pass

    rules = [
      RootRule(A),
      d_from_c,
      SingletonRule(B, B()),
    ]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    # This error message could note near matches like the singleton.
    self.assert_equal_with_printing(dedent("""
                                      Rules with errors: 1
                                        (D, [Select(C)], d_from_c):
                                          No rule was available to compute C with parameter type A
                                      """).strip(),
                                    str(cm.exception))

  def test_not_fulfillable_duplicated_dependency(self):
    # If a rule depends on another rule+subject in two ways, and one of them is unfulfillable
    # Only the unfulfillable one should be in the errors.

    @rule(B, [Select(D)])
    def b_from_d(d):
      pass

    @rule(D, [Select(A), Select(SubA)])
    def d_from_a_and_suba(a, suba):
      _ = yield Get(A, C, C())  # noqa: F841

    @rule(A, [Select(C)])
    def a_from_c(c):
      pass

    rules = _suba_root_rules + [
      b_from_d,
      d_from_a_and_suba,
      a_from_c,
    ]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(dedent("""
                      Rules with errors: 2
                        (B, [Select(D)], b_from_d):
                          No rule was available to compute D with parameter type SubA
                        (D, [Select(A), Select(SubA)], [Get(A, C)], d_from_a_and_suba):
                          No rule was available to compute A with parameter type SubA
                      """).strip(),
        str(cm.exception))

  assert_equal_with_printing = assert_equal_with_printing


class RuleGraphMakerTest(unittest.TestCase):
  # TODO HasProducts?

  def test_smallest_full_test(self):
    @rule(Exactly(A), [Select(SubA)])
    def a_from_suba(suba):
      pass

    rules = _suba_root_rules + [
      RootRule(SubA),
      a_from_suba,
    ]
    fullgraph = self.create_full_graph(rules)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, [Select(SubA)], a_from_suba) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], a_from_suba) for SubA" -> {"Param(SubA)"}
                     }""").strip(), fullgraph)

  def test_full_graph_for_planner_example(self):
    symbol_table = TargetTable()
    address_mapper = AddressMapper(JsonParser(symbol_table), '*.BUILD.json')
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
    @rule(A, [Select(SubA)])
    def a_from_suba(suba):
      pass

    @rule(B, [Select(A)])
    def b_from_a(a):
      pass

    rules = [
      RootRule(SubA),
      RootRule(A),
      a_from_suba,
      b_from_a,
    ]
    fullgraph = self.create_full_graph(rules)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: A, SubA
                       // root entries
                         "Select(A) for A" [color=blue]
                         "Select(A) for A" -> {"Param(A)"}
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, [Select(SubA)], a_from_suba) for SubA"}
                         "Select(B) for A" [color=blue]
                         "Select(B) for A" -> {"(B, [Select(A)], b_from_a) for A"}
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, [Select(A)], b_from_a) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], a_from_suba) for SubA" -> {"Param(SubA)"}
                         "(B, [Select(A)], b_from_a) for A" -> {"Param(A)"}
                         "(B, [Select(A)], b_from_a) for SubA" -> {"(A, [Select(SubA)], a_from_suba) for SubA"}
                     }""").strip(),
                     fullgraph)

  def test_single_rule_depending_on_subject_selection(self):
    @rule(Exactly(A), [Select(SubA)])
    def a_from_suba(suba):
      pass

    rules = [
      a_from_suba,
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, [Select(SubA)], a_from_suba) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], a_from_suba) for SubA" -> {"Param(SubA)"}
                     }""").strip(),
      subgraph)

  def test_multiple_selects(self):
    @rule(Exactly(A), [Select(SubA), Select(B)])
    def a_from_suba_and_b(suba, b):
      pass

    @rule(B, [])
    def b():
      pass

    rules = [
      a_from_suba_and_b,
      b,
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, [Select(SubA), Select(B)], a_from_suba_and_b) for SubA"}
                       // internal entries
                         "(A, [Select(SubA), Select(B)], a_from_suba_and_b) for SubA" -> {"(B, [], b) for ()" "Param(SubA)"}
                         "(B, [], b) for ()" -> {}
                     }""").strip(),
      subgraph)

  def test_one_level_of_recursion(self):
    @rule(Exactly(A), [Select(B)])
    def a_from_b(b):
      pass

    @rule(B, [Select(SubA)])
    def b_from_suba(suba):
      pass

    rules = [
      a_from_b,
      b_from_suba,
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, [Select(B)], a_from_b) for SubA"}
                       // internal entries
                         "(A, [Select(B)], a_from_b) for SubA" -> {"(B, [Select(SubA)], b_from_suba) for SubA"}
                         "(B, [Select(SubA)], b_from_suba) for SubA" -> {"Param(SubA)"}
                     }""").strip(),
      subgraph)

  def test_noop_removal_in_subgraph(self):
    @rule(Exactly(A), [Select(C)])
    def a_from_c(c):
      pass

    @rule(Exactly(A), [])
    def a():
      pass

    rules = [
      a_from_c,
      a,
      SingletonRule(B, B()),
    ]

    subgraph = self.create_subgraph(A, rules, SubA(), validate=False)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for ()" [color=blue]
                         "Select(A) for ()" -> {"(A, [], a) for ()"}
                       // internal entries
                         "(A, [], a) for ()" -> {}
                     }""").strip(),
      subgraph)

  def test_noop_removal_full_single_subject_type(self):
    @rule(Exactly(A), [Select(C)])
    def a_from_c(c):
      pass

    @rule(Exactly(A), [])
    def a():
      pass

    rules = _suba_root_rules + [
      a_from_c,
      a,
    ]

    fullgraph = self.create_full_graph(rules, validate=False)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for ()" [color=blue]
                         "Select(A) for ()" -> {"(A, [], a) for ()"}
                       // internal entries
                         "(A, [], a) for ()" -> {}
                     }""").strip(),
      fullgraph)

  def test_root_tuple_removed_when_no_matches(self):
    @rule(A, [Select(C)])
    def a_from_c(c):
      pass

    @rule(B, [Select(D), Select(A)])
    def b_from_d_and_a(d, a):
      pass

    rules = [
      RootRule(C),
      RootRule(D),
      a_from_c,
      b_from_d_and_a,
    ]

    fullgraph = self.create_full_graph(rules, validate=False)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: C, D
                       // root entries
                         "Select(A) for C" [color=blue]
                         "Select(A) for C" -> {"(A, [Select(C)], a_from_c) for C"}
                         "Select(B) for (C+D)" [color=blue]
                         "Select(B) for (C+D)" -> {"(B, [Select(D), Select(A)], b_from_d_and_a) for (C+D)"}
                       // internal entries
                         "(A, [Select(C)], a_from_c) for C" -> {"Param(C)"}
                         "(B, [Select(D), Select(A)], b_from_d_and_a) for (C+D)" -> {"(A, [Select(C)], a_from_c) for C" "Param(D)"}
                     }""").strip(),
      fullgraph)

  def test_noop_removal_transitive(self):
    # If a noop-able rule has rules that depend on it,
    # they should be removed from the graph.

    @rule(Exactly(B), [Select(C)])
    def b_from_c(c):
      pass

    @rule(Exactly(A), [Select(B)])
    def a_from_b(b):
      pass

    @rule(Exactly(A), [])
    def a():
      pass

    rules = [
      b_from_c,
      a_from_b,
      a,
    ]
    subgraph = self.create_subgraph(A, rules, SubA(), validate=False)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for ()" [color=blue]
                         "Select(A) for ()" -> {"(A, [], a) for ()"}
                       // internal entries
                         "(A, [], a) for ()" -> {}
                     }""").strip(),
      subgraph)

  def test_get_with_matching_singleton(self):
    @rule(Exactly(A), [Select(SubA)])
    def a_from_suba(suba):
      _ = yield Get(B, C, C())  # noqa: F841

    rules = [
      a_from_suba,
      SingletonRule(B, B()),
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, [Select(SubA)], [Get(B, C)], a_from_suba) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], [Get(B, C)], a_from_suba) for SubA" -> {"Param(SubA)" "Singleton(B(), B)"}
                     }""").strip(),
      subgraph)

  def test_depends_on_multiple_one_noop(self):
    @rule(B, [Select(A)])
    def b_from_a(a):
      pass

    @rule(A, [Select(C)])
    def a_from_c(c):
      pass

    @rule(A, [Select(SubA)])
    def a_from_suba(suba):
      pass

    rules = [
     b_from_a,
      a_from_c,
      a_from_suba,
    ]

    subgraph = self.create_subgraph(B, rules, SubA(), validate=False)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, [Select(A)], b_from_a) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], a_from_suba) for SubA" -> {"Param(SubA)"}
                         "(B, [Select(A)], b_from_a) for SubA" -> {"(A, [Select(SubA)], a_from_suba) for SubA"}
                     }""").strip(),
      subgraph)

  def test_multiple_depend_on_same_rule(self):
    @rule(B, [Select(A)])
    def b_from_a(a):
      pass

    @rule(C, [Select(A)])
    def c_from_a(a):
      pass

    @rule(A, [Select(SubA)])
    def a_from_suba(suba):
      pass

    rules = _suba_root_rules + [
      b_from_a,
      c_from_a,
      a_from_suba,
    ]

    subgraph = self.create_full_graph(rules)

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for SubA" [color=blue]
                         "Select(A) for SubA" -> {"(A, [Select(SubA)], a_from_suba) for SubA"}
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, [Select(A)], b_from_a) for SubA"}
                         "Select(C) for SubA" [color=blue]
                         "Select(C) for SubA" -> {"(C, [Select(A)], c_from_a) for SubA"}
                       // internal entries
                         "(A, [Select(SubA)], a_from_suba) for SubA" -> {"Param(SubA)"}
                         "(B, [Select(A)], b_from_a) for SubA" -> {"(A, [Select(SubA)], a_from_suba) for SubA"}
                         "(C, [Select(A)], c_from_a) for SubA" -> {"(A, [Select(SubA)], a_from_suba) for SubA"}
                     }""").strip(),
      subgraph)

  def test_get_simple(self):
    @rule(Exactly(A), [])
    def a():
      _ = yield Get(B, D, D())  # noqa: F841

    @rule(B, [Select(D)])
    def b_from_d(d):
      pass

    rules = [
      a,
      b_from_d,
    ]

    subgraph = self.create_subgraph(A, rules, SubA())

    self.assert_equal_with_printing(dedent("""
                     digraph {
                       // root subject types: SubA
                       // root entries
                         "Select(A) for ()" [color=blue]
                         "Select(A) for ()" -> {"(A, [], [Get(B, D)], a) for ()"}
                       // internal entries
                         "(A, [], [Get(B, D)], a) for ()" -> {"(B, [Select(D)], b_from_d) for D"}
                         "(B, [Select(D)], b_from_d) for D" -> {"Param(D)"}
                     }""").strip(),
                                    subgraph)

  def test_validate_yield_statements(self):
    expected_rx_str = re.escape("""\
Yield(value=Call(func=Name(id='A', ctx=Load()), args=[], keywords=[], starargs=None, kwargs=None))
""")
    with self.assertRaisesRegexp(_RuleVisitor.YieldVisitError, expected_rx_str):
      @rule(A, [])
      def f():
        yield A()

    expected_rx_str = re.escape("""\
Yield(value=Call(func=Name(id='Get', ctx=Load()), args=[\
Name(id='B', ctx=Load()), Name(id='D', ctx=Load()), \
Call(func=Name(id='D', ctx=Load()), args=[], keywords=[], starargs=None, kwargs=None)], \
keywords=[], starargs=None, kwargs=None))
""")
    with self.assertRaisesRegexp(_RuleVisitor.YieldVisitError, expected_rx_str):
      @rule(A, [])
      def g():
        yield Get(B, D, D())
        yield A()
        return

  def test_validate_yield_error_location(self):
    with self.assertRaises(_RuleVisitor.YieldVisitError) as cm:
      @rule(A, [])
      def f():
        yield A()
    exc_msg = str(cm.exception)
    # Correctly matches the function name.
    self.assertIn('In function f:', exc_msg)
    # Matches the line number of the @rule decorator.
    match_regexp = re.compile(r'^.*test_rules.py:{}:'.format(sys._getframe().f_lineno - 7),
                              flags=re.MULTILINE)
    assertRegex(self, exc_msg, match_regexp)
    # Shows sufficient context around the rule definition to locate it.
    self.assertIn("""\
      @rule(A, [])
      def f():
""", exc_msg)

  def create_full_graph(self, rules, validate=True):
    scheduler = create_scheduler(rules, validate=validate)
    return "\n".join(scheduler.rule_graph_visualization())

  def create_subgraph(self, requested_product, rules, subject, validate=True):
    scheduler = create_scheduler(rules + _suba_root_rules, validate=validate)
    return "\n".join(scheduler.rule_subgraph_visualization(type(subject), requested_product))

  assert_equal_with_printing = assert_equal_with_printing
