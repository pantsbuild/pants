# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from abc import abstractmethod, abstractproperty
from collections import OrderedDict

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
    self._root_subject_types = root_subject_types
    self._node_builder = node_builder
    self._goal_to_product = goal_to_product

  def validate(self):
    self._validate_task_rules()

  def _validate_task_rules(self):
    """ Validates that all tasks can be executed based on the defined product types and selectors.

    It checks
     - all products selected by tasks are produced by some task or intrinsic, or come from a root
      subject type
     - all goal products are also produced
    """
    intrinsics = self._node_builder._intrinsics
    serializable_tasks = self._node_builder._tasks
    root_subject_types = self._root_subject_types
    task_and_intrinsic_product_types = self._flatten_type_constraints(serializable_tasks.keys())
    task_and_intrinsic_product_types.update(product_type for _, product_type in self._flatten_type_constraints(intrinsics.keys()))

    projected_subject_types = set()
    dependency_subject_types = set()
    for rules_of_type_x in serializable_tasks.values():
      for rule in rules_of_type_x:
        for select in rule.input_selectors:
          if type(select) is SelectProjection:
            projected_subject_types.add(select.projected_subject)
          elif type(select) is SelectDependencies:
            dependency_subject_types.update(select.field_types)

    type_collections = {
      'product types': task_and_intrinsic_product_types,
      'root subject types': root_subject_types,
      'projected subject types': projected_subject_types,
      'dependency subject types': dependency_subject_types
    }

    for goal, goal_product in self._goal_to_product.items():
      if goal_product not in task_and_intrinsic_product_types:
        # NB: We could also check goals of the Goal type to see if the products they request are
        # also available.
        raise ValueError('no task for product used by goal "{}": {}'.format(goal, goal_product))

    validation_results = self._check_task_selectors(serializable_tasks, type_collections)
    results_with_warnings = [r for r in validation_results if r.has_warnings()]
    results_with_errors = [r for r in validation_results if r.has_errors()]

    if results_with_warnings:
      warning_listing = '\n  '.join('{}\n    {}'.format(result.rule, '\n    '.join(result.warnings))
                                    for result in results_with_warnings)
      logger.warn('Found {} rules with warnings:\n  {}'.format(len(results_with_warnings),
                                                               warning_listing))

    if results_with_errors:
      error_listing = '\n  '.join('{}\n    {}'.format(result.rule, '\n    '.join(result.errors))
                                  for result in results_with_errors)
      error_message = 'Found {} rules with errors:\n  {}'.format(len(results_with_errors),
                                                                 error_listing)
      raise ValueError(error_message)

  def _check_task_selectors(self, serializable_tasks, type_collections):
    validation_results = {}
    for rules_of_type_x in serializable_tasks.values():
      for rule in rules_of_type_x:
        if rule in validation_results:
          # NB If the rule is in the index more than once, don't validate it again.
          continue
        rule_errors = []
        rule_warnings = []
        for select in rule.input_selectors:
          if type(select) is Select:
            selection_products = [select.product]
          elif type(select) is SelectDependencies:
            selection_products = [select.dep_product, select.product]
          elif type(select) is SelectProjection:
            selection_products = [select.input_product, select.product]
          elif type(select) is SelectVariant:
            selection_products = [select.product]
          else:
            selection_products = []

          selection_products = self._flatten_type_constraints(selection_products)

          for selection_product in selection_products:
            err_msg = self._validate_product_is_provided(select,
                                                         selection_product,
                                                         type_collections)
            if err_msg:
              rule_errors.append(err_msg)
        result = RuleValidationResult(rule, rule_errors, rule_warnings)
        if not result.valid():
          validation_results[rule] = result
    return validation_results.values()

  def _validate_product_is_provided(self, select, selection_product_type, type_collections_by_name):
    if any(selection_product_type in types_in_collection
           for types_in_collection in type_collections_by_name.values()):
      return None
    else:
      err_msg = 'There is no producer of {}'.format(select)
      return err_msg

  def _flatten_type_constraints(self, selection_products):
    type_constraints = filter(lambda o: isinstance(o, Exactly), selection_products)
    non_type_constraints = filter(lambda o: not isinstance(o, Exactly), selection_products)
    flattened_products = OrderedSet(non_type_constraints)
    for t in type_constraints:
      flattened_products.update(t.types)
    return flattened_products


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
