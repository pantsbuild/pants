# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import logging
from abc import abstractmethod, abstractproperty
from collections import defaultdict

from pants.engine.isolated_process import ProcessExecutionNode, SnapshotNode
from pants.engine.nodes import (DependenciesNode, FilesystemNode, ProjectionNode, SelectNode,
                                TaskNode, collect_item_of_type)
from pants.engine.objects import Closable
from pants.engine.selectors import (Select, SelectDependencies, SelectLiteral, SelectProjection,
                                    SelectVariant)
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class Rule(object):
  """Marker class for rules."""

  @abstractproperty
  def output_product_type(self):
    """The product type produced by this rule."""

  @abstractmethod
  def as_node(self, subject, variants):
    """Constructs a ProductGraph node for this rule."""


class CoercionRule(datatype('CoercionRule', ['requested_type', 'available_type']), Rule):
  """Defines a task for converting from the available type to the requested type using the selection
  rules from Select.

  TODO: remove this by introducing union types as product types for tasks.
  """

  def __new__(cls, *args, **kwargs):
    factory = super(CoercionRule, cls).__new__(cls, *args, **kwargs)
    factory.input_selects = (Select(factory.available_type),)
    factory.func = functools.partial(coerce_fn, factory.requested_type)
    factory.func.__name__ = 'coerce'
    return factory

  @property
  def output_product_type(self):
    return self.requested_type

  def as_node(self, subject, variants):
    return TaskNode(subject, variants, self.requested_type, self.func, self.input_selects)


class TaskNodeFactory(datatype('TaskNodeFactory', ['input_selects', 'task_func', 'product_type']), Rule):
  """A set-friendly curried TaskNode constructor."""

  def as_node(self, subject, variants):
    return TaskNode(subject, variants, self.product_type, self.task_func, self.input_selects)

  @property
  def output_product_type(self):
    return self.product_type

  def __str__(self):
    return '({}, {!r}, {})'.format(self.product_type.__name__, self.input_selects, self.task_func.__name__)


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
    task_and_intrinsic_product_types = set(serializable_tasks.keys())
    task_and_intrinsic_product_types.update(product_type for _, product_type in intrinsics.keys())

    projected_subject_types = set()
    dependency_subject_types = set()
    for rules_of_type_x in serializable_tasks.values():
      for rule in rules_of_type_x:
        for select in rule.input_selects:
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
    validation_results = []
    for rules_of_type_x in serializable_tasks.values():
      for rule in rules_of_type_x:
        rule_errors = []
        rule_warnings = []
        for select in rule.input_selects:
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

          for selection_product in selection_products:
            err_msg, warn_msg = self._validate_product_is_provided(select,
                                                                   selection_product,
                                                                   type_collections)
            if err_msg:
              rule_errors.append(err_msg)
            if warn_msg:
              rule_warnings.append(warn_msg)
        result = RuleValidationResult(rule, rule_errors, rule_warnings)
        if not result.valid():
          validation_results.append(result)
    return validation_results

  def _validate_product_is_provided(self, select, selection_product_type, type_collections_by_name):
    if any(selection_product_type in types_in_collection
           for types_in_collection in type_collections_by_name.values()):
      return None, None

    def superclass_of_selection(current_type):
      return issubclass(selection_product_type, current_type)

    def subclass_of_selection(current_type):
      return issubclass(current_type, selection_product_type)

    super_types_by_name = {name: filter(superclass_of_selection, types) for name, types in
      type_collections_by_name.items()}
    sub_types_by_name = {name: filter(subclass_of_selection, types) for name, types in
      type_collections_by_name.items()}

    if (all(len(super_types) == 0 for super_types in super_types_by_name.values()) and all(
        len(sub_types) == 0 for sub_types in sub_types_by_name.values())):
      # doesn't cover HasProducts relationships or projections since they have middle
      # implicit types
      err_msg = 'There is no producer of {} or a super/subclass of it'.format(select)
      return err_msg, None
    else:
      warn_msg = 'There is only an indirect producer of {}. '.format(select)
      for name in type_collections_by_name.keys():
        if super_types_by_name.get(name):
          warn_msg += ' has supertyped {}: {}'.format(name, super_types_by_name[name])
        if sub_types_by_name.get(name):
          warn_msg += ' has subtyped {}: {}'.format(name, sub_types_by_name[name])
      return None, warn_msg


def coerce_fn(klass, obj):
  """Returns the passed object iff it is of the type klass, or returns a  product of the object if
  it has products of the right type.
  """
  return collect_item_of_type(klass, obj, None)


class NodeBuilder(Closable):
  """Holds an index of tasks and intrinsics used to instantiate Nodes."""

  @classmethod
  def create(cls, task_entries):
    """Creates a NodeBuilder with tasks indexed by their output type."""
    serializable_tasks = defaultdict(set)
    for entry in task_entries:
      if isinstance(entry, Rule):
        serializable_tasks[entry.output_product_type].add(entry)
      elif isinstance(entry, (tuple, list)) and len(entry) == 3:
        output_type, input_selects, task = entry
        serializable_tasks[output_type].add(TaskNodeFactory(tuple(input_selects),
                                                            task,
                                                            output_type))
      else:
        raise TypeError("Unexpected rule type: {}."
                        " Rules either extend Rule, or are 3 elem tuples.".format(type(entry)))

    intrinsics = dict()
    intrinsics.update(FilesystemNode.as_intrinsics())
    intrinsics.update(SnapshotNode.as_intrinsics())
    return cls(serializable_tasks, intrinsics)

  def __init__(self, tasks, intrinsics):
    self._tasks = tasks
    self._intrinsics = intrinsics

  def gen_nodes(self, subject, product_type, variants):
    # Intrinsics that provide the requested product for the current subject type.
    intrinsic_node_factory = self._lookup_intrinsic(product_type, subject)
    if intrinsic_node_factory:
      yield intrinsic_node_factory(subject, product_type, variants)
    else:
      # Tasks that provide the requested product.
      for node_factory in self._lookup_tasks(product_type):
        yield node_factory(subject, variants)

  def _lookup_tasks(self, product_type):
    for entry in self._tasks[product_type]:
      yield entry.as_node

  def _lookup_intrinsic(self, product_type, subject):
    return self._intrinsics.get((type(subject), product_type))

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


class SnapshottedProcess(datatype('SnapshottedProcess', ['product_type',
                                                         'binary_type',
                                                         'input_selectors',
                                                         'input_conversion',
                                                         'output_conversion']), Rule):
  """A task type for defining execution of snapshotted processes."""

  def as_node(self, subject, variants):
    return ProcessExecutionNode(subject, variants, self)

  @property
  def output_product_type(self):
    return self.product_type

  @property
  def input_selects(self):
    return self.input_selectors
