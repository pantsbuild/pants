# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from abc import abstractmethod, abstractproperty
from collections import OrderedDict, deque
from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.engine.addressable import Exactly
from pants.engine.fs import Files, PathGlobs
from pants.engine.isolated_process import ProcessExecutionNode, Snapshot, SnapshotNode
from pants.engine.nodes import (DependenciesNode, FilesystemNode, ProjectionNode, SelectNode,
                                TaskNode)
from pants.engine.objects import Closable
from pants.engine.selectors import (Select, SelectDependencies, SelectLiteral, SelectProjection,
                                    SelectVariant, type_or_constraint_repr)
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class Rule(AbstractClass):
  """Rules declare how to produce products for the product graph.

  A rule describes what dependencies must be provided to produce a particular product. They also act
  as factories for constructing the nodes within the graph.
  """

  @abstractproperty
  def input_selectors(self):
    """collection of input selectors"""

  @abstractproperty
  def output_product_type(self):
    """The product type produced by this rule."""

  @abstractmethod
  def as_node(self, subject, variants):
    """Constructs a ProductGraph node for this rule."""


class TaskRule(datatype('TaskRule', ['input_selectors', 'task_func', 'product_type', 'constraint']),
               Rule):
  """A Rule that runs a task function when all of its input selectors are satisfied."""

  def as_node(self, subject, variants):
    return TaskNode(subject, variants, self)

  @property
  def output_product_type(self):
    return self.product_type

  def __str__(self):
    return '({}, {!r}, {})'.format(type_or_constraint_repr(self.product_type),
                                   self.input_selectors,
                                   self.task_func.__name__)


class RuleValidationResult(datatype('RuleValidationResult', ['rule', 'errors', 'warnings'])):
  """Container for errors and warnings found during rule validation."""

  def valid(self):
    return len(self.errors) == 0 and len(self.warnings) == 0

  def has_warnings(self):
    return len(self.warnings) > 0

  def has_errors(self):
    return len(self.errors) > 0


class RulesetValidator(object):
  """Validates that the set of rules used by the node builder has no missing tasks.

  """

  def __init__(self, node_builder, goal_to_product, root_subject_types):
    if not root_subject_types:
      raise ValueError('root_subject_types must not be empty')
    self._root_subject_types = root_subject_types
    self._node_builder = node_builder
    self._goal_to_product = goal_to_product

    self._graph = GraphMaker(node_builder, goal_to_product, root_subject_types).full_graph()

  def validate(self):
    """ Validates that all tasks can be executed based on the declared product types and selectors.

    It checks
     - all products selected by tasks are produced by some task or intrinsic, or come from a root
      subject type
     - all goal products are also produced
    """


    error_message = self._graph.error_message()
    if error_message:
      raise ValueError(error_message)
    task_and_intrinsic_product_types = tuple(r.output_product_type for r in self._graph.root_rules)
    self._validate_goal_products(task_and_intrinsic_product_types)

  def _validate_goal_products(self, task_and_intrinsic_product_types):
    for goal, goal_product in self._goal_to_product.items():
      if goal_product not in task_and_intrinsic_product_types:
        # NB: We could also check goals of the Goal type to see if the products they request are
        # also available.
        raise ValueError(
          'no task for product used by goal "{}": {}'.format(goal, goal_product.__name__))


class SnapshottedProcess(datatype('SnapshottedProcess', ['product_type',
                                                         'binary_type',
                                                         'input_selectors',
                                                         'input_conversion',
                                                         'output_conversion']),
                         Rule):
  """A rule type for defining execution of snapshotted processes."""

  def as_node(self, subject, variants):
    return ProcessExecutionNode(subject, variants, self)

  @property
  def output_product_type(self):
    return self.product_type


class FilesystemIntrinsicRule(datatype('FilesystemIntrinsicRule', ['subject_type', 'product_type']),
                              Rule):
  """Intrinsic rule for filesystem operations."""

  @classmethod
  def as_intrinsics(cls):
    """Returns a dict of tuple(sbj type, product type) -> functions returning a fs node for that subject product type tuple."""
    return {(subject_type, product_type): FilesystemIntrinsicRule(subject_type, product_type)
      for product_type, subject_type in FilesystemNode._FS_PAIRS}

  def as_node(self, subject, variants):
    assert type(subject) is self.subject_type
    return FilesystemNode.create(subject, self.product_type, variants)

  @property
  def input_selectors(self):
    return tuple()

  @property
  def output_product_type(self):
    return self.product_type


class SnapshotIntrinsicRule(Rule):
  """Intrinsic rule for snapshot process execution."""

  output_product_type = Snapshot
  input_selectors = (Select(Files),)

  def as_node(self, subject, variants):
    assert type(subject) in (Files, PathGlobs)
    return SnapshotNode.create(subject, variants)

  @classmethod
  def as_intrinsics(cls):
    snapshot_intrinsic_rule = cls()
    return {
      (Files, Snapshot): snapshot_intrinsic_rule,
      (PathGlobs, Snapshot): snapshot_intrinsic_rule
    }

  def __repr__(self):
    return '{}()'.format(type(self).__name__)


class NodeBuilder(Closable):
  """Holds an index of tasks and intrinsics used to instantiate Nodes."""

  @classmethod
  def create(cls, task_entries, intrinsic_providers=(FilesystemIntrinsicRule, SnapshotIntrinsicRule)):
    """Creates a NodeBuilder with tasks indexed by their output type."""
    # NB make tasks ordered so that gen ordering is deterministic.
    serializable_tasks = OrderedDict()

    def add_task(product_type, rule):
      if product_type not in serializable_tasks:
        serializable_tasks[product_type] = OrderedSet()
      serializable_tasks[product_type].add(rule)

    for entry in task_entries:
      if isinstance(entry, Rule):
        add_task(entry.output_product_type, entry)
      elif isinstance(entry, (tuple, list)) and len(entry) == 3:
        output_type, input_selectors, task = entry
        if isinstance(output_type, Exactly):
          constraint = output_type
        elif isinstance(output_type, type):
          constraint = Exactly(output_type)
        else:
          raise TypeError("Unexpected product_type type {}, for rule {}".format(output_type, entry))

        factory = TaskRule(tuple(input_selectors), task, output_type, constraint)
        for kind in constraint.types:
          # NB Ensure that interior types from SelectDependencies / SelectProjections work by indexing
          # on the list of types in the constraint.

          add_task(kind, factory)
        add_task(constraint, factory)
      else:
        raise TypeError("Unexpected rule type: {}."
                        " Rules either extend Rule, or are 3 elem tuples.".format(type(entry)))

    intrinsics = dict()
    for provider in intrinsic_providers:
      as_intrinsics = provider.as_intrinsics()
      for k in as_intrinsics.keys():
        if k in intrinsics:
          # TODO Test ME!
          raise ValueError('intrinsic with subject-type, product-type {} defined by {} would overwrite a previous intrinsic'.format(k, provider))
      intrinsics.update(as_intrinsics)
    return cls(serializable_tasks, intrinsics)

  def __init__(self, tasks, intrinsics):
    self._tasks = tasks
    self._intrinsics = intrinsics

  def gen_rules(self, subject_type, product_type):
    # Intrinsics that provide the requested product for the current subject type.
    intrinsic_node_factory = self._lookup_intrinsic(product_type, subject_type)
    if intrinsic_node_factory:
      yield intrinsic_node_factory
    else:
      # Tasks that provide the requested product.
      for node_factory in self._lookup_tasks(product_type):
        yield node_factory

  def gen_nodes(self, subject, product_type, variants):
    for rule in self.gen_rules(type(subject), product_type):
      yield rule.as_node(subject, variants)

  def _lookup_tasks(self, product_type):
    for entry in self._tasks.get(product_type, tuple()):
      yield entry

  def _lookup_intrinsic(self, product_type, subject_type):
    return self._intrinsics.get((subject_type, product_type))

  def select_node(self, selector, subject, variants):
    """Constructs a Node for the given Selector and the given Subject/Variants.

    This method is decoupled from Selector classes in order to allow the `selector` package to not
    need a dependency on the `nodes` package.
    """
    selector_type = type(selector)
    if selector_type is Select:
      return SelectNode(subject, variants, selector)
    if selector_type is SelectVariant:
      return SelectNode(subject, variants, selector)
    elif selector_type is SelectLiteral:
      # NB: Intentionally ignores subject parameter to provide a literal subject.
      return SelectNode(selector.subject, variants, selector)
    elif selector_type is SelectDependencies:
      return DependenciesNode(subject, variants, selector)
    elif selector_type is SelectProjection:
      return ProjectionNode(subject, variants, selector)
    else:
      raise TypeError('Unrecognized Selector type "{}" for: {}'.format(selector_type, selector))


class Graph(datatype('Graph', ['root_subject', 'root_rules', 'rule_dependencies', 'failure_reasons'])):
  # TODO constructing nodes from the resulting graph
  # method, walk out from root nodes, constructing each node
  # when hit a node that can't be constructed yet, ie changes subject, collect those for later
  # inject the nodes into the product graph
  # schedule leaves from walk

  def error_message(self):
    """Prints list of errors for each errored rule with attribution."""
    collated_errors = OrderedDict()
    for wrapped_rule, diagnostic in self.failure_reasons.items():

      if wrapped_rule.rule not in collated_errors:
        collated_errors[wrapped_rule.rule] = OrderedDict()
      if diagnostic.reason not in collated_errors[wrapped_rule.rule]:
        collated_errors[wrapped_rule.rule][diagnostic.reason] = set()

      collated_errors[wrapped_rule.rule][diagnostic.reason].add(diagnostic.subject_type)

    used_rule_lookup = set(r.rule for r in self.rule_dependencies.keys())
    def format_messages(r, subject_types_by_reasons):
      errors = '\n    '.join('{} with subject types: {}'.format(reason, ', '.join(t.__name__ for t in subject_types))
        for reason, subject_types in subject_types_by_reasons.items())
      return '{}:\n    {}'.format(r, errors)

    formatted_messages = tuple(format_messages(r, subject_types_by_reasons) for r, subject_types_by_reasons in
    collated_errors.items() if r not in used_rule_lookup)
    if not formatted_messages:
      return None
    return 'Rules with errors: {}\n  {}'.format(len(formatted_messages), '\n  '.join(formatted_messages))

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

  @property
  def output_product_type(self):
    return self.rule.output_product_type

  def __repr__(self):
    return '{}({}, {})'.format(type(self).__name__, self.subject_type.__name__, self.rule)

  def __str__(self):
    return '{} of {}'.format(self.rule, self.subject_type.__name__)


class Diagnostic(datatype('Diagnostic', ['rule', 'subject_type', 'reason', 'other_rules'])):
  """Holds on to error reasons for problems with the build graph."""


class GraphMaker(object):

  def __init__(self, nodebuilder, goal_to_product=None, root_subject_types=None):
    self.root_subject_types = root_subject_types
    self.goal_to_product = goal_to_product
    self.nodebuilder = nodebuilder
    if root_subject_types is None:
      raise ValueError("TODO")

  def _find_rhs_for_select(self, subject_type, selector):
    original_genned_rules = tuple(WithSubject(subject_type, r) for r in self.nodebuilder.gen_rules(subject_type, selector.product))
    if selector.type_constraint.type_satisfies(subject_type):
      # if the subject will match, it's always picked first and we ignore other possible rules.
      return (SubjectIsProduct(subject_type),)
    else:
      return original_genned_rules

  def get(self, subject, requested_product):
    root_subject = subject
    root_subject_type = type(root_subject)
    return Graph(root_subject, *self._get(root_subject_type, requested_product))

  def _get(self, root_subject_type, requested_product):
    root_rules = tuple(WithSubject(root_subject_type, r)
      for r in self.nodebuilder.gen_rules(root_subject_type, requested_product))

    rule_dependency_edges = OrderedDict()

    unfulfillable_rules = OrderedDict()
    rules_to_traverse = deque(root_rules)

    def add_rules_to_graph(rule, dep_rules):
      rules_to_traverse.extend(g for g in dep_rules if g not in rule_dependency_edges)
      if rule not in rule_dependency_edges:
        rule_dependency_edges[rule] = dep_rules
      else:
        rule_dependency_edges[rule] += dep_rules

    while rules_to_traverse:
      rule = rules_to_traverse.popleft()
      if type(rule) in (Literal, SubjectIsProduct):
        continue

      if type(rule) is not WithSubject:
        raise TypeError("rules must all be WithSubject'ed")

      subject_type = rule.subject_type
      was_unfulfillable = False
      # TODO it might be good to note which selectors deps are attached to,
      # TODO then when eliminating nodes, we can be sure that the right things are eliminated
      for selector in rule.input_selectors:
        # TODO cycles, because it should handle that
        if type(selector) is Select:
          # TODO, handle Addresses / Variants
          rules_or_literals_for_selector = self._find_rhs_for_select(subject_type,
            selector)

          if not rules_or_literals_for_selector:
            unfulfillable_rules[rule] = Diagnostic(rule, subject_type, 'no matches for {}'.format(selector), None)
            was_unfulfillable = True
            break # from the selector loop
          add_rules_to_graph(rule, rules_or_literals_for_selector)

        elif type(selector) is SelectDependencies:
          initial_selector = Select(selector.dep_product)
          initial_rules_or_literals = self._find_rhs_for_select(subject_type, initial_selector)
          if not initial_rules_or_literals:
            unfulfillable_rules[rule] = Diagnostic(rule, subject_type, 'no matches for {} when resolving {}'.format(initial_selector, selector), None)
            was_unfulfillable = True
            break # from the selector loop

          synth_rules = self._synth_rules_for_select_deps(selector)
          if not synth_rules:
            selector_for_product = Select(selector.product)
            unfulfillable_rules[rule] = Diagnostic(rule, selector.field_types, 'no matches for {} when resolving {}'.format(selector_for_product, selector), None)
            was_unfulfillable = True
            break # from selector loop

          add_rules_to_graph(rule, initial_rules_or_literals)
          add_rules_to_graph(rule, tuple(synth_rules))
        elif type(selector) is SelectLiteral:
          add_rules_to_graph(rule, (Literal(selector.subject, selector.product),))
        elif type(selector) is SelectProjection:
          # TODO, could validate that input product has fields

          initial_projection_selector = Select(selector.input_product)
          initial_projection_rules_or_literals = self._find_rhs_for_select(subject_type, initial_projection_selector)
          if not initial_projection_rules_or_literals:
            unfulfillable_rules[rule]=Diagnostic(rule, subject_type, 'no matches for {} when resolving {}'.format(initial_projection_selector, selector), None)
            was_unfulfillable = True
            break

          projected_selector = Select(selector.product)
          synth_rules_for_projection = self._find_rhs_for_select(selector.projected_subject, projected_selector)
          if not synth_rules_for_projection:
            unfulfillable_rules[rule]=Diagnostic(rule, selector.projected_subject, 'no matches for {} when resolving {}'.format(projected_selector, selector), None)
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

    return root_rules, rule_dependency_edges, unfulfillable_rules

  def _synth_rules_for_select_deps(self, selector):
    synth_rules = []
    for field_type in selector.field_types:
      rules_or_literals_for_field_type = self._find_rhs_for_select(field_type, Select(selector.product))
      if not rules_or_literals_for_field_type:
        print(
          'Hm. this type cant be fulfilled for this dependency {} {}'.format(field_type, selector))
        continue
      synth_rules.extend(rules_or_literals_for_field_type)
    return synth_rules

  def _remove_unfulfillable_rules_and_dependents(self, root_rules, rule_dependency_edges,
    unfulfillable_rules):
    removal_traversal = deque(unfulfillable_rules.keys())
    while removal_traversal:
      rule = removal_traversal.pop()
      for cur, deps in tuple(rule_dependency_edges.items()):
        if cur in unfulfillable_rules:
          continue
        if rule in deps:
          # If there are no other potential providers of the type
          # that rule provided, then also mark the current rule as unfulfillable
          if all(d.output_product_type is not rule.output_product_type
                 for d in deps if d is not rule and type(d) not in (Literal, SubjectIsProduct)):
            unfulfillable_rules[cur] = Diagnostic(cur,
              cur.subject_type,
              'depends on unfulfillable {}'.format(rule), None)
            removal_traversal.append(cur)
          else:
            rule_dependency_edges[cur]= tuple(d for d in deps if d != rule)

    rule_dependency_edges = OrderedDict(
      (k, v) for k, v in rule_dependency_edges.items() if k not in unfulfillable_rules)
    root_rules = tuple(r for r in root_rules if r not in unfulfillable_rules)
    return root_rules, rule_dependency_edges

  def full_graph(self):
    full_root_rules = OrderedSet()
    full_dependency_edges = OrderedDict()
    full_unfulfillable_rules = OrderedDict()
    for r in self.root_subject_types:
      for p in self.all_produced_product_types(r):
        # TODO might want to pass the current root rules / dependency edges through.
        root_rules, rule_dependency_edges, unfulfillable_rules = self._get(r, p)
        full_root_rules.update(root_rules)
        full_dependency_edges.update(rule_dependency_edges)
        full_unfulfillable_rules.update(unfulfillable_rules)
    return FullGraph(self.root_subject_types, list(full_root_rules), full_dependency_edges, full_unfulfillable_rules)

  def all_produced_product_types(self, subject_type):
    intrinsic_products = [prod for subj, prod in self.nodebuilder._intrinsics.keys() if subj == subject_type]
    task_products = self.nodebuilder._tasks.keys()
    return intrinsic_products + task_products
