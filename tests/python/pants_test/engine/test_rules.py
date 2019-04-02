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
from pants.engine.selectors import Get
from pants_test.engine.examples.parsers import JsonParser
from pants_test.engine.util import (TARGET_TABLE, assert_equal_with_printing, create_scheduler,
                                    run_rule)
from pants_test.test_base import TestBase


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


_this_is_not_a_type = 3


@console_rule('example', [Console])
def a_console_rule_generator(console):
  a = yield Get(A, str('a str!'))
  console.print_stdout(str(a))


class RuleTest(unittest.TestCase):
  def test_run_rule_console_rule_generator(self):
    res = run_rule(a_console_rule_generator, Console(), {
        (A, str): lambda _: A(),
      })
    self.assertEquals(res, _GoalProduct.for_name('example')())


class RuleIndexTest(TestBase):
  def test_creation_fails_with_bad_declaration_type(self):
    with self.assertRaisesWithMessage(TypeError, """\
Rule entry A() had an unexpected type: <class 'pants_test.engine.test_rules.A'>. Rules either extend Rule or UnionRule, or are static functions decorated with @rule."""):
      RuleIndex.create([A()])


class RuleGraphTest(TestBase):
  def test_ruleset_with_missing_product_type(self):
    @rule(A, [B])
    def a_from_b_noop(b):
      pass

    rules = _suba_root_rules + [a_from_b_noop]

    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, [B], a_from_b_noop()):
                         No rule was available to compute B with parameter type SubA
                     """).strip(),
                                    str(cm.exception))

  def test_ruleset_with_ambiguity(self):
    @rule(A, [C, B])
    def a_from_c_and_b(c, b):
      pass

    @rule(A, [B, C])
    def a_from_b_and_c(b, c):
      pass

    @rule(D, [A])
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
                       (D, [A], d_from_a()):
                         Ambiguous rules to compute A with parameter types (B+C):
                           (A, [B, C], a_from_b_and_c()) for (B+C)
                           (A, [C, B], a_from_c_and_b()) for (B+C)
                     """).strip(),
      str(cm.exception))

  def test_ruleset_with_rule_with_two_missing_selects(self):
    @rule(A, [B, C])
    def a_from_b_and_c(b, c):
      pass

    rules = _suba_root_rules + [a_from_b_and_c]
    with self.assertRaises(Exception) as cm:
      create_scheduler(rules)

    self.assert_equal_with_printing(dedent("""
                     Rules with errors: 1
                       (A, [B, C], a_from_b_and_c()):
                         No rule was available to compute B with parameter type SubA
                         No rule was available to compute C with parameter type SubA
                     """).strip(),
      str(cm.exception))

  def test_ruleset_with_selector_only_provided_as_root_subject(self):
    @rule(A, [B])
    def a_from_b(b):
      pass

    rules = [RootRule(B), a_from_b]
    create_scheduler(rules)

  def test_ruleset_with_superclass_of_selected_type_produced_fails(self):
    @rule(A, [B])
    def a_from_b(b):
      pass

    @rule(B, [SubA])
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
                                        (A, [B], a_from_b()):
                                          No rule was available to compute B with parameter type C
                                        (B, [SubA], b_from_suba()):
                                          No rule was available to compute SubA with parameter type C
                                      """).strip(),
                                    str(cm.exception))

  def test_ruleset_with_failure_due_to_incompatible_subject_for_singleton(self):
    @rule(D, [C])
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
                                        (D, [C], d_from_c()):
                                          No rule was available to compute C with parameter type A
                                      """).strip(),
                                    str(cm.exception))

  def test_not_fulfillable_duplicated_dependency(self):
    # If a rule depends on another rule+subject in two ways, and one of them is unfulfillable
    # Only the unfulfillable one should be in the errors.

    @rule(B, [D])
    def b_from_d(d):
      pass

    @rule(D, [A, SubA])
    def d_from_a_and_suba(a, suba):
      _ = yield Get(A, C, C())  # noqa: F841

    @rule(A, [C])
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
                        (B, [D], b_from_d()):
                          No rule was available to compute D with parameter type SubA
                        (D, [A, SubA], [Get(A, C)], d_from_a_and_suba()):
                          No rule was available to compute A with parameter type SubA
                      """).strip(),
        str(cm.exception))

  def test_smallest_full_test(self):
    @rule(A, [SubA])
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
                         "Select(A) for SubA" -> {"(A, [SubA], a_from_suba()) for SubA"}
                       // internal entries
                         "(A, [SubA], a_from_suba()) for SubA" -> {"Param(SubA)"}
                     }""").strip(), fullgraph)

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
    @rule(A, [SubA])
    def a_from_suba(suba):
      pass

    @rule(B, [A])
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
                         "Select(A) for SubA" -> {"(A, [SubA], a_from_suba()) for SubA"}
                         "Select(B) for A" [color=blue]
                         "Select(B) for A" -> {"(B, [A], b_from_a()) for A"}
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, [A], b_from_a()) for SubA"}
                       // internal entries
                         "(A, [SubA], a_from_suba()) for SubA" -> {"Param(SubA)"}
                         "(B, [A], b_from_a()) for A" -> {"Param(A)"}
                         "(B, [A], b_from_a()) for SubA" -> {"(A, [SubA], a_from_suba()) for SubA"}
                     }""").strip(),
                     fullgraph)

  def test_single_rule_depending_on_subject_selection(self):
    @rule(A, [SubA])
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
                         "Select(A) for SubA" -> {"(A, [SubA], a_from_suba()) for SubA"}
                       // internal entries
                         "(A, [SubA], a_from_suba()) for SubA" -> {"Param(SubA)"}
                     }""").strip(),
      subgraph)

  def test_multiple_selects(self):
    @rule(A, [SubA, B])
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
                         "Select(A) for SubA" -> {"(A, [SubA, B], a_from_suba_and_b()) for SubA"}
                       // internal entries
                         "(A, [SubA, B], a_from_suba_and_b()) for SubA" -> {"(B, [], b()) for ()" "Param(SubA)"}
                         "(B, [], b()) for ()" -> {}
                     }""").strip(),
      subgraph)

  def test_potentially_ambiguous_get(self):
    # In this case, we validate that a Get is satisfied by a rule that actually consumes its
    # parameter, rather than by having the same dependency rule consume a parameter that was
    # already in the context.
    #
    # This accounts for the fact that when someone uses Get (rather than Select), it's because
    # they intend for the Get's parameter to be consumed in the subgraph. Anything else would
    # be surprising.
    @rule(A, [SubA])
    def a(sub_a):
      _ = yield Get(B, C())  # noqa: F841

    @rule(B, [SubA])
    def b_from_suba(suba):
      pass

    @rule(SubA, [C])
    def suba_from_c(c):
      pass

    rules = [
      a,
      b_from_suba,
      suba_from_c,
    ]

    subgraph = self.create_subgraph(A, rules, SubA())
    self.assert_equal_with_printing(
        dedent("""
            digraph {
              // root subject types: SubA
              // root entries
                "Select(A) for SubA" [color=blue]
                "Select(A) for SubA" -> {"(A, [SubA], [Get(B, C)], a()) for SubA"}
              // internal entries
                "(A, [SubA], [Get(B, C)], a()) for SubA" -> {"(B, [SubA], b_from_suba()) for C" "Param(SubA)"}
                "(B, [SubA], b_from_suba()) for C" -> {"(SubA, [C], suba_from_c()) for C"}
                "(B, [SubA], b_from_suba()) for SubA" -> {"Param(SubA)"}
                "(SubA, [C], suba_from_c()) for C" -> {"Param(C)"}
            }
        """).strip(),
        subgraph,
      )

  def test_one_level_of_recursion(self):
    @rule(A, [B])
    def a_from_b(b):
      pass

    @rule(B, [SubA])
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
                         "Select(A) for SubA" -> {"(A, [B], a_from_b()) for SubA"}
                       // internal entries
                         "(A, [B], a_from_b()) for SubA" -> {"(B, [SubA], b_from_suba()) for SubA"}
                         "(B, [SubA], b_from_suba()) for SubA" -> {"Param(SubA)"}
                     }""").strip(),
      subgraph)

  def test_noop_removal_in_subgraph(self):
    @rule(A, [C])
    def a_from_c(c):
      pass

    @rule(A, [])
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
                         "Select(A) for ()" -> {"(A, [], a()) for ()"}
                       // internal entries
                         "(A, [], a()) for ()" -> {}
                     }""").strip(),
      subgraph)

  def test_noop_removal_full_single_subject_type(self):
    @rule(A, [C])
    def a_from_c(c):
      pass

    @rule(A, [])
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
                         "Select(A) for ()" -> {"(A, [], a()) for ()"}
                       // internal entries
                         "(A, [], a()) for ()" -> {}
                     }""").strip(),
      fullgraph)

  def test_root_tuple_removed_when_no_matches(self):
    @rule(A, [C])
    def a_from_c(c):
      pass

    @rule(B, [D, A])
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
                         "Select(A) for C" -> {"(A, [C], a_from_c()) for C"}
                         "Select(B) for (C+D)" [color=blue]
                         "Select(B) for (C+D)" -> {"(B, [D, A], b_from_d_and_a()) for (C+D)"}
                       // internal entries
                         "(A, [C], a_from_c()) for C" -> {"Param(C)"}
                         "(B, [D, A], b_from_d_and_a()) for (C+D)" -> {"(A, [C], a_from_c()) for C" "Param(D)"}
                     }""").strip(),
      fullgraph)

  def test_noop_removal_transitive(self):
    # If a noop-able rule has rules that depend on it,
    # they should be removed from the graph.

    @rule(B, [C])
    def b_from_c(c):
      pass

    @rule(A, [B])
    def a_from_b(b):
      pass

    @rule(A, [])
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
                         "Select(A) for ()" -> {"(A, [], a()) for ()"}
                       // internal entries
                         "(A, [], a()) for ()" -> {}
                     }""").strip(),
      subgraph)

  def test_get_with_matching_singleton(self):
    @rule(A, [SubA])
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
                         "Select(A) for SubA" -> {"(A, [SubA], [Get(B, C)], a_from_suba()) for SubA"}
                       // internal entries
                         "(A, [SubA], [Get(B, C)], a_from_suba()) for SubA" -> {"Param(SubA)" "Singleton(B(), B)"}
                     }""").strip(),
      subgraph)

  def test_depends_on_multiple_one_noop(self):
    @rule(B, [A])
    def b_from_a(a):
      pass

    @rule(A, [C])
    def a_from_c(c):
      pass

    @rule(A, [SubA])
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
                         "Select(B) for SubA" -> {"(B, [A], b_from_a()) for SubA"}
                       // internal entries
                         "(A, [SubA], a_from_suba()) for SubA" -> {"Param(SubA)"}
                         "(B, [A], b_from_a()) for SubA" -> {"(A, [SubA], a_from_suba()) for SubA"}
                     }""").strip(),
      subgraph)

  def test_multiple_depend_on_same_rule(self):
    @rule(B, [A])
    def b_from_a(a):
      pass

    @rule(C, [A])
    def c_from_a(a):
      pass

    @rule(A, [SubA])
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
                         "Select(A) for SubA" -> {"(A, [SubA], a_from_suba()) for SubA"}
                         "Select(B) for SubA" [color=blue]
                         "Select(B) for SubA" -> {"(B, [A], b_from_a()) for SubA"}
                         "Select(C) for SubA" [color=blue]
                         "Select(C) for SubA" -> {"(C, [A], c_from_a()) for SubA"}
                       // internal entries
                         "(A, [SubA], a_from_suba()) for SubA" -> {"Param(SubA)"}
                         "(B, [A], b_from_a()) for SubA" -> {"(A, [SubA], a_from_suba()) for SubA"}
                         "(C, [A], c_from_a()) for SubA" -> {"(A, [SubA], a_from_suba()) for SubA"}
                     }""").strip(),
      subgraph)

  def test_get_simple(self):
    @rule(A, [])
    def a():
      _ = yield Get(B, D, D())  # noqa: F841

    @rule(B, [D])
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
                         "Select(A) for ()" -> {"(A, [], [Get(B, D)], a()) for ()"}
                       // internal entries
                         "(A, [], [Get(B, D)], a()) for ()" -> {"(B, [D], b_from_d()) for D"}
                         "(B, [D], b_from_d()) for D" -> {"Param(D)"}
                     }""").strip(),
                                    subgraph)

  def test_invalid_get_arguments(self):
    with self.assertRaisesWithMessage(ValueError, """\
Could not resolve type `XXX` in top level of module pants_test.engine.test_rules"""):
      class XXX(object): pass
      @rule(A, [])
      def f():
        a = yield Get(A, XXX, 3)
        yield a

    # This fails because the argument is defined in this file's module, but it is not a type.
    with self.assertRaisesWithMessage(ValueError, """\
Expected a `type` constructor for `_this_is_not_a_type`, but got: 3 (type `int`)"""):
      @rule(A, [])
      def g():
        a = yield Get(A, _this_is_not_a_type, 3)
        yield a

  def test_validate_yield_statements_in_rule_body(self):
    with self.assertRaisesRegexp(_RuleVisitor.YieldVisitError, re.escape('yield A()')):
      @rule(A, [])
      def f():
        yield A()
        # The yield statement isn't at the end of this series of statements.
        return

    with self.assertRaises(_RuleVisitor.YieldVisitError) as cm:
      @rule(A, [])
      def h():
        yield A(
          1 + 2
        )
        return
    # Test that the full indentation of multiple-line yields are represented in the output.
    self.assertIn("""\
        yield A(
          1 + 2
        )
""", str(cm.exception))

    with self.assertRaises(_RuleVisitor.YieldVisitError) as cm:
      @rule(A, [])
      def g():
        # This is a yield statement without an assignment, and not at the end.
        yield Get(B, D, D())
        yield A()
    exc_msg = str(cm.exception)
    exc_msg_trimmed = re.sub(r'^.*?(test_rules\.py)', r'\1', exc_msg, flags=re.MULTILINE)
    self.assertEquals(exc_msg_trimmed, """\
In function g: yield in @rule without assignment must come at the end of a series of statements.

A yield in an @rule without an assignment is equivalent to a return, and we
currently require that no statements follow such a yield at the same level of nesting.
Use `_ = yield Get(...)` if you wish to yield control to the engine and discard the result.

The invalid statement was:
test_rules.py:{lineno}:{col}
        yield Get(B, D, D())

The rule defined by function `g` begins at:
test_rules.py:{rule_lineno}:{rule_col}
      @rule(A, [])
      def g():
        # This is a yield statement without an assignment, and not at the end.
        yield Get(B, D, D())
        yield A()
""".format(lineno=(sys._getframe().f_lineno - 22),
           col=8,
           rule_lineno=(sys._getframe().f_lineno - 27),
           rule_col=6))

  def create_full_graph(self, rules, validate=True):
    scheduler = create_scheduler(rules, validate=validate)
    return "\n".join(scheduler.rule_graph_visualization())

  def create_subgraph(self, requested_product, rules, subject, validate=True):
    scheduler = create_scheduler(rules + _suba_root_rules, validate=validate)
    return "\n".join(scheduler.rule_subgraph_visualization(type(subject), requested_product))

  assert_equal_with_printing = assert_equal_with_printing
