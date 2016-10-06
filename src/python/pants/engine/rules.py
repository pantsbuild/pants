# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from abc import abstractmethod, abstractproperty
from collections import OrderedDict, defaultdict, deque
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

  def __init__(self, node_builder, goal_to_product, root_subject_fns):
    if not root_subject_fns:
      raise ValueError('root_subject_fns must not be empty')
    self._goal_to_product = goal_to_product

    self._graph = GraphMaker(node_builder, root_subject_fns).full_graph()

  def validate(self):
    """ Validates that all tasks can be executed based on the declared product types and selectors.

    It checks
     - all products selected by tasks are produced by some task or intrinsic, or come from a root
      subject type
     - all goal products are also produced
    """

    # TODO cycles, because it should handle that.
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
          # NB Ensure that interior types from SelectDependencies / SelectProjections work by
          # indexing on the list of types in the constraint.
          add_task(kind, factory)
        add_task(constraint, factory)
      else:
        raise TypeError("Unexpected rule type: {}."
                        " Rules either extend Rule, or are 3 elem tuples.".format(type(entry)))

    intrinsics = dict()
    for provider in intrinsic_providers:
      as_intrinsics = provider.as_intrinsics()
      duplicate_keys = [k for k in as_intrinsics.keys() if k in intrinsics]
      if duplicate_keys:
        key_list = '\n  '.join('{}, {}'.format(sub.__name__, prod.__name__)
                                for sub, prod in duplicate_keys)
        raise ValueError('intrinsics provided by {} have already provided subject-type, '
                         'product-type keys:\n  {}'.format(provider, key_list))
      intrinsics.update(as_intrinsics)
    return cls(serializable_tasks, intrinsics)

  def __init__(self, tasks, intrinsics):
    self._tasks = tasks
    self._intrinsics = intrinsics

  def all_rules(self):
    """Returns a set containing all rules including instrinsics."""
    declared_rules = set(rule for rules_for_product in self._tasks.values()
                         for rule in rules_for_product)
    declared_intrinsics = set(rule for rule in self._intrinsics.values())
    return declared_rules.union(declared_intrinsics)

  def all_produced_product_types(self, subject_type):
    intrinsic_products = set(prod for subj, prod in self._intrinsics.keys()
                             if subj == subject_type)
    task_products = self._tasks.keys()
    return intrinsic_products.union(set(task_products))

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


class CanHaveDependencies(object):
  """Marker class for graph entries that can have dependencies on other graph entries."""
  input_selectors = None
  subject_type = None


class CanBeDependency(object):
  """Marker class for graph entries that are leaves, and can be depended upon."""


class RuleGraph(datatype('RuleGraph',
                         ['root_subject_types',
                          'root_rules',
                          'rule_dependencies',
                          'unfulfillable_rules'])):
  """A graph containing rules mapping rules to their dependencies taking into account subject types.

  This is a graph of rules. It models dependencies between rules, along with the subject types for
  those rules. This allows the resulting graph to include cases where a selector is fulfilled by the
  subject of the graph.

  Because in

     `root_subject_types` the root subject types this graph was generated with.
     `root_rules` The rule entries that can produce the root products this graph was generated
                        with.
     `rule_dependencies` A map from rule entries to the rule entries they depend on.
                         The collections of dependencies are contained by RuleEdges objects.
                         Keys must be subclasses of CanHaveDependencies
                         values must be subclasses of CanBeDependency
     `unfulfillable_rules` A map of rule entries to collections of Diagnostics
                                 containing the reasons why they were eliminated from the graph.

  """
  # TODO constructing nodes from the resulting graph.
  # Possible approach:
  # - walk out from root nodes, constructing each node.
  # - when hit a node that can't be constructed yet, ie the subject type changes,
  #   skip and collect for later.
  # - inject the constructed nodes into the product graph.

  def error_message(self):
    """Returns a nice error message for errors in the rule graph."""
    collated_errors = defaultdict(lambda : defaultdict(set))
    for rule_entry, diagnostics in self.unfulfillable_rules.items():
      # don't include the root rules in the error
      # message since they aren't real.
      if type(rule_entry) is RootRule:
        continue
      for diagnostic in diagnostics:
        collated_errors[rule_entry.rule][diagnostic.reason].add(diagnostic.subject_type)

    def subject_type_str(t):
      if t is None:
        return 'Any'
      elif type(t) is type:
        return t.__name__
      elif type(t) is tuple:
        return ', '.join(x.__name__ for x in t)
      else:
        return str(t)

    def format_messages(rule, subject_types_by_reasons):
      errors = '\n    '.join(sorted('{} with subject types: {}'
                             .format(reason, ', '.join(sorted(subject_type_str(t) for t in subject_types)))
                             for reason, subject_types in subject_types_by_reasons.items()))
      return '{}:\n    {}'.format(rule, errors)

    used_rule_lookup = set(rule_entry.rule for rule_entry in self.rule_dependencies.keys())
    formatted_messages = sorted(format_messages(rule, subject_types_by_reasons)
                               for rule, subject_types_by_reasons in collated_errors.items()
                               if rule not in used_rule_lookup)
    if not formatted_messages:
      return None
    return 'Rules with errors: {}\n  {}'.format(len(formatted_messages),
                                                '\n  '.join(formatted_messages))

  def __str__(self):
    if not self.root_rules:
      return '{empty graph}'

    root_subject_types_str = ', '.join(x.__name__ for x in self.root_subject_types)
    root_rules_str = ', '.join(sorted(str(r) for r in self.root_rules))
    return dedent("""
              {{
                root_subject_types: ({},)
                root_rules: {}
                {}
              }}""".format(root_subject_types_str,
                           root_rules_str,
                           '\n                '.join(self._dependency_strs())
    )).strip()

  def _dependency_strs(self):
    return sorted('{} => ({},)'.format(rule, ', '.join(str(d) for d in deps))
                  for rule, deps in self.rule_dependencies.items())


class RuleGraphSubjectIsProduct(datatype('RuleGraphSubjectIsProduct', ['value']), CanBeDependency):
  """Wrapper for when the dependency is the subject."""

  @property
  def output_product_type(self):
    return self.value

  def __repr__(self):
    return '{}({})'.format(type(self).__name__, self.value.__name__)

  def __str__(self):
    return 'SubjectIsProduct({})'.format(self.value.__name__)


class RuleGraphLiteral(datatype('RuleGraphLiteral', ['value', 'product_type']), CanBeDependency):
  """The dependency is the literal value held by SelectLiteral."""

  @property
  def output_product_type(self):
    return self.product_type

  def __repr__(self):
    return '{}({}, {})'.format(type(self).__name__, self.value, self.product_type.__name__)

  def __str__(self):
    return 'Literal({}, {})'.format(self.value, self.product_type.__name__)


class RuleGraphEntry(datatype('RuleGraphEntry', ['subject_type', 'rule']),
                     CanBeDependency,
                     CanHaveDependencies):
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


class RootRule(datatype('RootRule', ['subject_type', 'selector']), CanHaveDependencies):
  """A synthetic rule representing a root selector."""

  @property
  def input_selectors(self):
    return (self.selector,)

  @property
  def output_product_type(self):
    return self.selector.product

  @property
  def rule(self):
    return self # might work

  def __str__(self):
    return '{} for {}'.format(self.selector, self.subject_type.__name__)


class Diagnostic(datatype('Diagnostic', ['subject_type', 'reason'])):
  """Holds on to error reasons for problems with the build graph."""


class UnreachableRule(object):
  """A rule entry that can't be reached."""

  def __init__(self, rule):
    self.rule = rule


class RuleEdges(object):
  """Represents the edges from a rule to its dependencies via selectors."""
  # TODO add a highwater mark count to count how many branches are eliminated

  def __init__(self, dependencies=tuple(), selector_to_deps=None):
    self._dependencies = dependencies
    if selector_to_deps is None:
      self._selector_to_deps = defaultdict(tuple)
    else:
      self._selector_to_deps = selector_to_deps

  def add_edges_via(self, selector, new_dependencies):
    if selector is None and new_dependencies:
      raise ValueError("Cannot specify a None selector with non-empty dependencies!")
    tupled_other_rules = tuple(new_dependencies)
    self._selector_to_deps[selector] += tupled_other_rules
    self._dependencies += tupled_other_rules

  def has_edges_for(self, selector):
    return selector in self._selector_to_deps

  def __contains__(self, rule):
    return rule in self._dependencies

  def __iter__(self):
    return self._dependencies.__iter__()

  def makes_unfulfillable(self, dep_to_eliminate):
    """Returns true if removing dep_to_eliminate makes this set of edges unfulfillable."""
    if len(self._dependencies) == 1 and self._dependencies[0] == dep_to_eliminate:
      return True
    for selector, deps in self._selector_to_deps.items():
      if len(deps) == 1 and dep_to_eliminate == deps[0]:
        return True
    else:
      return False

  def without_rule(self, dep_to_eliminate):
    new_selector_to_deps = defaultdict(tuple)
    for selector, deps in self._selector_to_deps.items():
      new_selector_to_deps[selector] = tuple(d for d in deps if d != dep_to_eliminate)

    return RuleEdges(tuple(d for d in self._dependencies if d != dep_to_eliminate),
                     new_selector_to_deps)


class GraphMaker(object):

  def __init__(self, nodebuilder, root_subject_fns):
    self.root_subject_selector_fns = root_subject_fns
    self.nodebuilder = nodebuilder

  def generate_subgraph(self, root_subject, requested_product):
    root_subject_type = type(root_subject)
    root_selector = self.root_subject_selector_fns[root_subject_type](requested_product)
    root_rules, edges, unfulfillable = self._construct_graph(RootRule(root_subject_type, root_selector))
    root_rules, edges = self._remove_unfulfillable_rules_and_dependents(root_rules,
      edges, unfulfillable)
    return RuleGraph((root_subject_type,), root_rules, edges, unfulfillable)

  def full_graph(self):
    """Produces a full graph based on the root subjects and all of the products produced by rules."""
    full_root_rules = set()
    full_dependency_edges = {}
    full_unfulfillable_rules = {}
    for root_subject_type, selector_fn in self.root_subject_selector_fns.items():
      for product in sorted(self.nodebuilder.all_produced_product_types(root_subject_type)):
        beginning_root = RootRule(root_subject_type, selector_fn(product))
        root_dependencies, rule_dependency_edges, unfulfillable_rules = self._construct_graph(
          beginning_root,
          root_rules=full_root_rules,
          rule_dependency_edges=full_dependency_edges,
          unfulfillable_rules=full_unfulfillable_rules
        )

        full_root_rules = set(root_dependencies)
        full_dependency_edges = rule_dependency_edges
        full_unfulfillable_rules = unfulfillable_rules

    rules_in_graph = set(entry.rule for entry in full_dependency_edges.keys())
    rules_eliminated_during_construction = set(entry.rule
                                               for entry in full_unfulfillable_rules.keys())

    declared_rules = self.nodebuilder.all_rules()
    unreachable_rules = declared_rules.difference(rules_in_graph,
                                                  rules_eliminated_during_construction)
    for rule in sorted(unreachable_rules):
      full_unfulfillable_rules[UnreachableRule(rule)] = [Diagnostic(None, 'Unreachable')]

    full_root_rules, full_dependency_edges = self._remove_unfulfillable_rules_and_dependents(
      full_root_rules,
      full_dependency_edges,
      full_unfulfillable_rules)

    return RuleGraph(self.root_subject_selector_fns,
                         list(full_root_rules),
                         full_dependency_edges,
                         full_unfulfillable_rules)

  def _construct_graph(self,
                       beginning_rule,
                       root_rules=None,
                       rule_dependency_edges=None,
                       unfulfillable_rules=None):
    root_rules = set() if root_rules is None else root_rules
    rule_dependency_edges = dict() if rule_dependency_edges is None else rule_dependency_edges
    unfulfillable_rules = dict() if unfulfillable_rules is None else unfulfillable_rules
    rules_to_traverse = deque([beginning_rule])

    def _find_rhs_for_select(subject_type, selector):
      if selector.type_constraint.satisfied_by_type(subject_type):
        # NB a matching subject is always picked first
        return (RuleGraphSubjectIsProduct(subject_type),)
      else:
        return tuple(RuleGraphEntry(subject_type, rule)
          for rule in self.nodebuilder.gen_rules(subject_type, selector.product))

    def mark_unfulfillable(rule, subject_type, reason):
      if rule not in unfulfillable_rules:
        unfulfillable_rules[rule] = []
      unfulfillable_rules[rule].append(Diagnostic(subject_type, reason))

    def add_rules_to_graph(rule, selector_path, dep_rules):
      unseen_dep_rules = [g for g in dep_rules
                          if g not in rule_dependency_edges and g not in unfulfillable_rules]
      rules_to_traverse.extend(unseen_dep_rules)
      if type(rule) is RootRule:
        root_rules.update(dep_rules)
        return
      elif rule not in rule_dependency_edges:
        new_edges = RuleEdges()
        new_edges.add_edges_via(selector_path, dep_rules)
        rule_dependency_edges[rule] = new_edges
      else:
        existing_deps = rule_dependency_edges[rule]
        if existing_deps.has_edges_for(selector_path):
          raise ValueError("rule {} already has dependencies set for selector {}"
                           .format(rule, selector_path))

        existing_deps.add_edges_via(selector_path, dep_rules)

    while rules_to_traverse:
      entry = rules_to_traverse.popleft()
      if isinstance(entry, CanBeDependency) and not isinstance(entry, CanHaveDependencies):
        continue
      if not isinstance(entry, CanHaveDependencies):
        raise TypeError("Cannot determine dependencies of entry not of type CanHaveDependencies: {}"
                        .format(entry))
      if entry in unfulfillable_rules:
        continue

      if entry in rule_dependency_edges:
        continue

      was_unfulfillable = False

      for selector in entry.input_selectors:
        if type(selector) in (Select, SelectVariant):
          # TODO, handle the Addresses / Variants case
          rules_or_literals_for_selector = _find_rhs_for_select(entry.subject_type, selector)
          if not rules_or_literals_for_selector:
            mark_unfulfillable(entry, entry.subject_type, 'no matches for {}'.format(selector))
            was_unfulfillable = True
            continue
          add_rules_to_graph(entry, selector, rules_or_literals_for_selector)
        elif type(selector) is SelectLiteral:
          add_rules_to_graph(entry,
                             selector,
                             (RuleGraphLiteral(selector.subject, selector.product),))
        elif type(selector) is SelectDependencies:
          initial_selector = selector.dep_product_selector
          initial_rules_or_literals = _find_rhs_for_select(entry.subject_type, initial_selector)
          if not initial_rules_or_literals:
            mark_unfulfillable(entry,
                               entry.subject_type,
                               'no matches for {} when resolving {}'
                               .format(initial_selector, selector))
            was_unfulfillable = True
            continue

          rules_for_dependencies = []
          for field_type in selector.field_types:
            rules_for_field_subjects = _find_rhs_for_select(field_type,
                                                            selector.projected_product_selector)
            rules_for_dependencies.extend(rules_for_field_subjects)

          if not rules_for_dependencies:
            mark_unfulfillable(entry,
                               selector.field_types,
                               'no matches for {} when resolving {}'
                               .format(selector.projected_product_selector, selector))
            was_unfulfillable = True
            continue

          add_rules_to_graph(entry,
                             (selector, selector.dep_product_selector),
                             initial_rules_or_literals)
          add_rules_to_graph(entry,
                             (selector, selector.projected_product_selector),
                             tuple(rules_for_dependencies))
        elif type(selector) is SelectProjection:
          # TODO, could validate that input product has fields
          initial_rules_or_literals = _find_rhs_for_select(entry.subject_type,
                                                           selector.input_product_selector)
          if not initial_rules_or_literals:
            mark_unfulfillable(entry,
                               entry.subject_type,
                               'no matches for {} when resolving {}'
                                .format(selector.input_product_selector, selector))
            was_unfulfillable = True
            continue

          projected_rules = _find_rhs_for_select(selector.projected_subject,
                                                 selector.projected_product_selector)
          if not projected_rules:
            mark_unfulfillable(entry,
                               selector.projected_subject,
                               'no matches for {} when resolving {}'
                               .format(selector.projected_product_selector, selector))
            was_unfulfillable = True
            continue

          add_rules_to_graph(entry,
                             (selector, selector.input_product_selector),
                             initial_rules_or_literals)
          add_rules_to_graph(entry,
                             (selector, selector.projected_product_selector),
                             projected_rules)
        else:
          raise TypeError('Unexpected type of selector: {}'.format(selector))
      if not was_unfulfillable and entry not in rule_dependency_edges:
        # NB: In this case, there are no selectors.
        add_rules_to_graph(entry, None, tuple())

    return root_rules, rule_dependency_edges, unfulfillable_rules

  def _remove_unfulfillable_rules_and_dependents(self,
                                                 root_rules,
                                                 rule_dependency_edges,
                                                 unfulfillable_rules):
    """Removes all unfulfillable rules transitively from the roots and the dependency edges.


    Takes the current root rule set and dependency table and removes all rules that are not
    transitively fulfillable.

    Deforestation. Leaping from tree to tree."""
    # could experiment with doing this for each rule added and deduping the traversal list
    removal_traversal = deque(unfulfillable_rules.keys())
    while removal_traversal:
      unfulfillable_entry = removal_traversal.popleft()
      for current_entry, dependency_edges in tuple(rule_dependency_edges.items()):
        if current_entry in unfulfillable_rules:
          # NB: these are removed at the end
          continue

        if dependency_edges.makes_unfulfillable(unfulfillable_entry):
          unfulfillable_rules[current_entry] = [Diagnostic(current_entry.subject_type,
                                                'depends on unfulfillable {}'.format(unfulfillable_entry))]
          removal_traversal.append(current_entry)
        else:
          rule_dependency_edges[current_entry] = dependency_edges.without_rule(unfulfillable_entry)

    rule_dependency_edges = dict((k, v) for k, v in rule_dependency_edges.items()
                                 if k not in unfulfillable_rules)
    root_rules = tuple(r for r in root_rules if r not in unfulfillable_rules)
    return root_rules, rule_dependency_edges
