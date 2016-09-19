# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from collections import deque
from textwrap import dedent

from twitter.common.collections import OrderedDict, OrderedSet

from pants.base.specs import DescendantAddresses, SiblingAddresses, SingleAddress
from pants.build_graph.address import Address
from pants.engine.addressable import Exactly
from pants.engine.fs import FileDigest, PathGlobs, create_fs_tasks
from pants.engine.graph import create_graph_tasks
from pants.engine.mapper import AddressMapper
from pants.engine.rules import NodeBuilder, Rule, RulesetValidator
from pants.engine.selectors import Select, SelectDependencies, SelectLiteral, SelectProjection
from pants.util.objects import datatype
from pants_test.engine.examples.parsers import JsonParser
from pants_test.engine.examples.planners import Goal
from pants_test.engine.test_mapper import TargetTable


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


class NodeBuilderTest(unittest.TestCase):
  def test_creation_fails_with_bad_declaration_type(self):
    with self.assertRaises(TypeError) as cm:
      NodeBuilder.create([A()])
    self.assertEquals("Unexpected rule type: <class 'pants_test.engine.test_rules.A'>."
                      " Rules either extend Rule, or are 3 elem tuples.",
                      str(cm.exception))


class RulesetValidatorTest(unittest.TestCase):
  def test_ruleset_with_missing_product_type(self):
    rules = [(A, (Select(B),), noop)]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_types=tuple())
    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assertEquals(dedent("""
                                Found 1 rules with errors:
                                  (A, (Select(B),), noop)
                                    There is no producer of Select(B)
                             """).strip(),
      str(cm.exception))

  def test_ruleset_with_rule_with_two_missing_selects(self):
    rules = [(A, (Select(B), Select(B)), noop)]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_types=tuple())
    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assertEquals(dedent("""
                                Found 1 rules with errors:
                                  (A, (Select(B), Select(B)), noop)
                                    There is no producer of Select(B)
                                    There is no producer of Select(B)
                             """).strip(),
      str(cm.exception))

  def test_ruleset_with_with_selector_only_provided_as_root_subject(self):

    validator = RulesetValidator(NodeBuilder.create([(A, (Select(B),), noop)]),
      goal_to_product=dict(),
      root_subject_types=(B,))

    validator.validate()

  def test_ruleset_with_superclass_of_selected_type_produced_fails(self):

    rules = [
      (A, (Select(B),), noop),
      (B, (Select(SubA),), noop)
    ]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_types=tuple())

    with self.assertRaises(ValueError) as cm:
      validator.validate()
    self.assertEquals(dedent("""
                                Found 1 rules with errors:
                                  (B, (Select(SubA),), noop)
                                    There is no producer of Select(SubA)
                             """).strip(), str(cm.exception))

  def test_ruleset_with_goal_not_produced(self):
    rules = [
      (B, (Select(SubA),), noop)
    ]

    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assertEquals("no task for product used by goal \"goal-name\": <class 'pants_test.engine.test_rules.AGoal'>",
                      str(cm.exception))

  def test_ruleset_with_explicit_type_constraint(self):
    rules = [
      (Exactly(A), (Select(B),), noop),
      (B, (Select(A),), noop)
    ]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_types=tuple())

    validator.validate()
# and now the in progress graph creation
#


class Graph(datatype('Graph', ['root_subject', 'root_rules', 'rule_dependencies'])):
  # TODO constructing nodes from the resulting graph
  # method, walk out from root nodes, constructing each node
  # when hit a node that can't be constructed yet, ie changes subject, collect those for later
  # inject the nodes into the product graph
  # schedule leaves from walk

  def __str__(self):
    if not self.root_rules:
      return '{empty graph}'
    def key(r):
      return '"{}"'.format(r)

    return dedent("""
              {{
                root_subject: {}
                root_rules: {}
                {}

              }}""".format(self.root_subject, ', '.join(key(r) for r in self.root_rules),
      '\n                '.join('{} => ({},)'.format(rule, ', '.join(str(d) for d in deps)) for rule, deps in self.rule_dependencies.items())
    )).strip()


class FullGraph(Graph):
  # TODO as a validation thing, go through the dependency edges keys.
  # if a rule in the declared rule set doesn't show up, then that means it is unreachable.
  # What's cool now, is that we could show that intrinsics are unreachable
  # Also, we can show the unreachability paths because we know the initial unreachable thing and each thing it caused to be unreachable.

  def __str__(self):
    if not self.root_rules:
      return '{empty graph}'
    def key(r):
      return '"{}"'.format(r)

    return dedent("""
              {{
                root_subject_types: ({},)
                root_rules: {}
                {}

              }}""".format(', '.join(x.__name__ for x in self.root_subject), ', '.join(key(r) for r in self.root_rules),
      '\n                '.join('{} => ({},)'.format(rule, ', '.join(str(d) for d in deps)) for rule, deps in self.rule_dependencies.items())
    )).strip()


class SubjectIsProduct(datatype('SubjectIsProduct', ['value'])):
  """Wrapper for when the dependency is the subject."""

  def __repr__(self):
    if isinstance(self.value, type):
      return '{}({})'.format(type(self).__name__, self.value.__name__)
    else:
      return '{}({})'.format(type(self).__name__, self.value)


class Literal(datatype('Literal', ['value', 'product_type'])):
  """The dependency is the literal value held by SelectLiteral."""

  def __repr__(self):
    return '{}({}, {})'.format(type(self).__name__, self.value, self.product_type.__name__)


class WithSubject(datatype('WithSubject', ['subject_type', 'rule'])):
  """A synthetic rule with a specified subject type"""

  @property
  def input_selectors(self):
    return self.rule.input_selectors

  def __repr__(self):
    return '{}({}, {})'.format(type(self).__name__, self.subject_type.__name__, self.rule)

  def __str__(self):
    return '{} of {}'.format(self.rule, self.subject_type.__name__)


class GraphMaker(object):

  def __init__(self, nodebuilder, goal_to_product=None, root_subject_types=None):
    self.root_subject_types = root_subject_types
    self.goal_to_product = goal_to_product
    self.nodebuilder = nodebuilder
    if root_subject_types is None:
      raise ValueError("TODO")
    # naive
    # take the node builder index,
    # do another pass where we make a map of rule -> initial set of dependencies
    # then when generating a subgraph, follow all the dep to dep lists until have to give up
    #

  def _blah_for_select(self, subject_type, selector):
    original_genned_rules = tuple(WithSubject(subject_type, r) for r in self.nodebuilder.gen_rules(subject_type, selector.product))
    if selector.type_constraint.type_satisfies(subject_type):
      # if the subject will match, it's always picked first and we ignore other possible rules.
      #genned_rules = (SubjectIsProduct(subject_type),) + original_genned_rules
      return (SubjectIsProduct(subject_type),)
    else:
      return original_genned_rules
    ##if not genned_rules:
     # return # something
    #return genned_rules

  def get(self, subject, requested_product):
    root_subject = subject
    root_subject_type = type(root_subject)
    return Graph(root_subject, *self._get(root_subject_type, requested_product))

  def _get(self, root_subject_type, requested_product):
    root_rules = tuple(WithSubject(root_subject_type, r)
                       for r in self.nodebuilder.gen_rules(root_subject_type, requested_product))

    rule_dependency_edges = OrderedDict()

    unfulfillable_rules = OrderedSet()
    rules_to_traverse = deque(root_rules)

    def add_rules_to_graph(rule, dep_rules):
      rules_to_traverse.extend(g for g in dep_rules if g not in rule_dependency_edges)
      if rule not in rule_dependency_edges:
        rule_dependency_edges[rule] = dep_rules
      else:
        rule_dependency_edges[rule] += dep_rules
        #raise ValueError('not sure what to do with this case, but I should write a test case for it')

    while rules_to_traverse:
      rule = rules_to_traverse.popleft()
      if type(rule) in (Literal, SubjectIsProduct):
        continue

      if type(rule) is WithSubject:
        #subject = rule.subject
        subject_type = rule.subject_type
      else:
        raise TypeError("rules must all be WithSubject'ed")

      was_unfulfillable = False
      for selector in rule.input_selectors:
        # TODO cycles, because it should handle that
        if type(selector) is Select:
          # TODO, handle Address / Variant weirdness
          rules_or_literals_for_selector = self._blah_for_select(subject_type,
            selector)

          if not rules_or_literals_for_selector:
            # NB rule is not fulfillable with this subject / product
            # - if the rule is not in rule_dependency_edges,
            print('rule not fulfillable by way of selector {}. rule {}'.format(selector, rule))
            unfulfillable_rules.add(rule)
            was_unfulfillable = True
            break # from the selector loop
          add_rules_to_graph(rule, rules_or_literals_for_selector)

        elif type(selector) is SelectDependencies:
          initial_selector = Select(selector.dep_product)
          initial_rules_or_literals = self._blah_for_select(subject_type, initial_selector)
          if not initial_rules_or_literals:
            print('initial selector for select dependencies cannot be fulfilled {}'.format(initial_selector))
            unfulfillable_rules.add(rule)
            was_unfulfillable = True
            break # from the selector loop
          synth_rules = self._synth_rules_for_select_deps(selector)

          print('synth_rules')
          print(synth_rules)

          if not synth_rules:
            print('no rules available for any field types used by {}'.format(selector))
            unfulfillable_rules.add(rule)
            was_unfulfillable = True
            break # from selector loop

          add_rules_to_graph(rule, initial_rules_or_literals)
          add_rules_to_graph(rule, tuple(synth_rules))
        elif type(selector) is SelectLiteral:
          add_rules_to_graph(rule, (Literal(selector.subject, selector.product),))
        elif type(selector) is SelectProjection:
          # TODO, could validate that input product has fields

          initial_projection_selector = Select(selector.input_product)
          initial_projection_rules_or_literals = self._blah_for_select(subject_type, initial_projection_selector)
          if not initial_projection_rules_or_literals:
            unfulfillable_rules.add(rule)
            was_unfulfillable = True
            break

          projected_selector = Select(selector.product)
          synth_rules_for_projection = self._blah_for_select(selector.projected_subject, projected_selector)

          if not synth_rules_for_projection:
            unfulfillable_rules.add(rule)
            was_unfulfillable = True
            break

          add_rules_to_graph(rule, initial_projection_rules_or_literals)
          add_rules_to_graph(rule, synth_rules_for_projection)
        else:
          raise TypeError('cant handle a {} selector yet'.format(selector))
      if not was_unfulfillable and rule not in rule_dependency_edges:
        rule_dependency_edges[rule] = tuple()

    root_rules, rule_dependency_edges = self._remove_unfulfillable_rules_and_dependents(root_rules,
      rule_dependency_edges, unfulfillable_rules)

    return root_rules, rule_dependency_edges

  def _synth_rules_for_select_deps(self, selector):
    synth_rules = []
    for field_type in selector.field_types:
      rules_or_literals_for_field_type = self._blah_for_select(field_type, Select(selector.product))
      if not rules_or_literals_for_field_type:
        print(
          'Hm. this type cant be fulfilled for this dependency {} {}'.format(field_type, selector))
        continue
      synth_rules.extend(rules_or_literals_for_field_type)
      # for r in rules_or_literals_for_field_type:
      #  synth_rules.append(WithSubject(field_type, r))
    return synth_rules

  def _remove_unfulfillable_rules_and_dependents(self, root_rules, rule_dependency_edges,
    unfulfillable_rules):
    removal_traversal = deque(unfulfillable_rules)
    while removal_traversal:
      rule = removal_traversal.pop()
      for cur, deps in rule_dependency_edges.items():
        if cur in unfulfillable_rules:
          continue
        if rule in deps:
          print('  removing {} because it depends on {}'.format(cur, rule))
          unfulfillable_rules.add(cur)
          removal_traversal.append(cur)

          # this doesn't hold, so don't do it
          #for dep in deps:
          #  if dep not in unfulfillable_rules:
          #    print('  removing {} because it was a dependency ')
          #    unfulfillable_rules.add(dep)
          #    removal_traversal.append(dep)
    rule_dependency_edges = OrderedDict(
      (k, v) for k, v in rule_dependency_edges.items() if k not in unfulfillable_rules)
    root_rules = tuple(r for r in root_rules if r not in unfulfillable_rules)
    print('final unfillable rule list:\n  {}'.format('\n  '.join(str(r) for r in unfulfillable_rules)))
    return root_rules, rule_dependency_edges

  def full_graph(self):
    full_root_rules = OrderedSet()
    full_dependency_edges = OrderedDict()
    for r in self.root_subject_types:
      for p in self.all_produced_product_types(r):
        # TODO might want to pass the current root rules / dependency edges through.
        root_rules, rule_dependency_edges = self._get(r, p)
        full_root_rules.update(root_rules)
        full_dependency_edges.update(rule_dependency_edges)
    return FullGraph(self.root_subject_types, list(full_root_rules), full_dependency_edges)

  def all_produced_product_types(self, subject_type):
    intrinsic_products = [prod for subj, prod in self.nodebuilder._intrinsics.keys() if subj == subject_type]
    task_products = self.nodebuilder._tasks.keys()
    return intrinsic_products + task_products


class PremadeGraphTest(unittest.TestCase):

  def test_smallest_full_test(self):
    rules = [
      (Exactly(A), (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=(SubA,))
    fullgraph = graphmaker.full_graph()
    #subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: "(Exactly(A), (Select(SubA),), noop) of SubA"
                                 (Exactly(A), (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)

                               }""").strip(), fullgraph)

  def test_hugest_full_test(self):
    symbol_table_cls = TargetTable
    address_mapper = AddressMapper(symbol_table_cls, JsonParser, '*.BUILD.json')
    tasks = create_graph_tasks(address_mapper, symbol_table_cls) + create_fs_tasks()

    rule_index = NodeBuilder.create(tasks)
    graphmaker = GraphMaker(rule_index,
      #goal_to_product={'goal-name': AGoal},
      root_subject_types=(Address,
                          PathGlobs,
                          SingleAddress,
                          SiblingAddresses,
                          DescendantAddresses,))
    fullgraph = graphmaker.full_graph()
    real_values = set()
    values = rule_index._tasks.values()
    for v in values:
      real_values.update(str(x) for x in v)
    s = set(str(r.rule) for r in fullgraph.rule_dependencies.keys())

    self.assertEquals(set(real_values.union(set(str(r) for r in rule_index._intrinsics.values()))),
      s
    )
    #subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
                               {
                                 root_subject_types: (SubA,)
                                 root_rules: "(Exactly(A), (Select(SubA),), noop) of SubA"
                                 (Exactly(A), (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)

                               }""").strip(), fullgraph)

  def test_smallest_full_test_multiple_root_subject_types(self):
    rules = [
      (Exactly(A), (Select(SubA),), noop),
      (Exactly(B), (Select(A),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=(SubA, A))
    fullgraph = graphmaker.full_graph()
    #subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
                               {
                                 root_subject_types: (SubA, A,)
                                 root_rules: "(Exactly(A), (Select(SubA),), noop) of SubA", "(Exactly(B), (Select(A),), noop) of SubA", "(Exactly(B), (Select(A),), noop) of A"
                                 (Exactly(A), (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                                 (Exactly(B), (Select(A),), noop) of SubA => ((Exactly(A), (Select(SubA),), noop) of SubA,)
                                 (Exactly(B), (Select(A),), noop) of A => (SubjectIsProduct(A),)

                               }""").strip(), fullgraph)

  # TODO something with variants
  def test_smallest_test(self):
    rules = [
      (Exactly(A), (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
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
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (Select(SubA), Select(B)), noop) of SubA"
                                 (Exactly(A), (Select(SubA), Select(B)), noop) of SubA => (SubjectIsProduct(SubA), (B, (), noop) of SubA,)
                                 (B, (), noop) of SubA => (,)

                               }""").strip(), subgraph)

  def test_one_level_of_recursion(self):
    #return
    rules = [
      (Exactly(A), (Select(B),), noop),
      (B, (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (Select(B),), noop) of SubA"
                                 (Exactly(A), (Select(B),), noop) of SubA => ((B, (Select(SubA),), noop) of SubA,)
                                 (B, (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)

                               }""").strip(), subgraph)

  def test_noop_removal(self):
    # there's one rule that will match and one that won't be fulfilled.
    # ah! intrinsics aren't fully covered by the validator. I'm betting
    # this one is just a direct one, not a transitive one
    intrinsics = {(B, C): BoringRule(C)}
    rules = [
      # C is provided by an intrinsic, but only if the subject is B.
      (Exactly(A), (Select(C),), noop),
      (Exactly(A), tuple(), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules,
                                               intrinsic_providers=(IntrinsicProvider(intrinsics),)),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (), noop) of SubA"
                                 (Exactly(A), (), noop) of SubA => (,)

                               }""").strip(), subgraph)

    def test_noop_removal_full_single_subject_type(self):
      # there's one rule that will match and one that won't be fulfilled.
      # ah! intrinsics aren't fully covered by the validator. I'm betting
      # this one is just a direct one, not a transitive one
      intrinsics = {(B, C): BoringRule(C)}
      rules = [
        # C is provided by an intrinsic, but only if the subject is B.
        (Exactly(A), (Select(C),), noop),
        (Exactly(A), tuple(), noop),
      ]

      graphmaker = GraphMaker(NodeBuilder.create(rules,
        intrinsic_providers=(IntrinsicProvider(intrinsics),)),
        goal_to_product={'goal-name': AGoal},
        root_subject_types=tuple([SubA]))
      fullgraph = graphmaker.full_graph()

      self.assert_blah(dedent("""
                                 {
                                   root_subject_types: SubA
                                   root_rules: "(Exactly(A), (), noop) of SubA"
                                   (Exactly(A), (), noop) of SubA => (,)

                                 }""").strip(), fullgraph)

  def test_noop_removal_transitive(self):
    # there's one rule that will match and one that won't be fulfilled.
    # ah! intrinsics aren't fully covered by the validator. I'm betting
    # this one is just a direct one, not a transitive one
    rules = [
      (Exactly(B), (Select(FileDigest),), noop),
      (Exactly(A), (Select(B),), noop),
      (Exactly(A), tuple(), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (), noop) of SubA"
                                 (Exactly(A), (), noop) of SubA => (,)

                               }""").strip(), subgraph)

  def test_select_dependencies_wut(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, C, field_types=(D,)),), noop),
      (B, (Select(D),), noop),
      (C, (Select(SubA),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (SelectDependencies(B, C, field_types=(D,)),), noop) of SubA"
                                 (Exactly(A), (SelectDependencies(B, C, field_types=(D,)),), noop) of SubA => ((C, (Select(SubA),), noop) of SubA, (B, (Select(D),), noop) of D,)
                                 (C, (Select(SubA),), noop) of SubA => (SubjectIsProduct(SubA),)
                                 (B, (Select(D),), noop) of D => (SubjectIsProduct(D),)

                               }""").strip(), subgraph)

  def test_select_dependencies_simpler(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(D,)),), noop),
      (B, (Select(D),), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
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
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
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
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
                                 {
                                   root_subject: SubA()
                                   root_rules: "(Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA"
                                   (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop) of SubA => (SubjectIsProduct(SubA), (B, (Select(C),), noop) of C, (B, (Select(C),), noop) of D,)
                                   (B, (Select(C),), noop) of C => (SubjectIsProduct(C),)
                                   (B, (Select(C),), noop) of D => ((C, (Select(D),), noop) of D,)
                                   (C, (Select(D),), noop) of D => (SubjectIsProduct(D),)

                                 }""").strip(), subgraph)

  #n_a_inthere_select_dependencies_multiple_field_types_all_resolvable_with_deps
  def test_what_happens_if_i_throw_a_bit_of_recursion_in_there(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C, D,)),), noop),
      (B, (Select(A),), noop),
      #()
      (C, (Select(SubA),), noop),
      (SubA, tuple(), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
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
  # rename all of the tests to be good

  def test_select_dependencies_non_matching_subselector_because_of_intrinsic(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(D,)),), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules,
      intrinsic_providers=(IntrinsicProvider({(C, B): BoringRule(B)}),)
    ),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah('{empty graph}', subgraph)

  def test_select_dependencies_with_matching_intrinsic(self):
    rules = [
      (Exactly(A), (SelectDependencies(B, SubA, field_types=(C,)),), noop),
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules,
      intrinsic_providers=(IntrinsicProvider({(C, B): BoringRule(B)}),)
    ),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
                               {
                                 root_subject: SubA()
                                 root_rules: "(Exactly(A), (SelectDependencies(B, SubA, field_types=(C,)),), noop) of SubA"
                                 (Exactly(A), (SelectDependencies(B, SubA, field_types=(C,)),), noop) of SubA => (SubjectIsProduct(SubA), BoringRule(B) of C,)
                                 BoringRule(B) of C => (,)

                               }""").strip(), subgraph)

  def test_select_literal(self):
    literally_a = A()
    rules = [
      (B, (SelectLiteral(literally_a, A),), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=B)

    self.assert_blah(dedent("""
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
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah(dedent("""
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
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah('{empty graph}', subgraph)

  def test_secondary_select_projection_failure(self):
    rules = [
      (Exactly(A), (SelectProjection(B, D, ('some',), C),), noop),
      (C, tuple(), noop)
    ]

    graphmaker = GraphMaker(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    subgraph = graphmaker.get(subject=SubA(), requested_product=A)

    self.assert_blah('{empty graph}', subgraph)

  def assert_blah(self, strip, subgraph):

    s = str(subgraph)
    print('Expected:')
    print(strip)
    print('Actual:')
    print(s)
    self.assertEqual(strip, s)
