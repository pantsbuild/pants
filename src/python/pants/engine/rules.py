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


class CoercionRule(datatype('CoercionFactory', ['requested_type', 'available_type']), Rule):
  """Defines a task for converting from the available type to the requested type using the selection
  rules from Select.

  TODO: remove this by introducing union types as product types for tasks.
  """

  def __new__(cls, *args, **kwargs):
    factory = super(CoercionRule, cls).__new__(cls, *args, **kwargs)
    factory.input_selects = (Select(factory.available_type),)
    factory.func = functools.partial(coerce_fn, factory.requested_type)
    return factory

  @property
  def output_product_type(self):
    return self.requested_type

  def as_node(self, subject, variants):
    return TaskNode(subject, variants, self.requested_type, self.func, self.input_selects)


class TaskNodeFactory(datatype('Task', ['input_selects', 'task_func', 'product_type']), Rule):
  """A set-friendly curried TaskNode constructor."""

  def as_node(self, subject, variants):
    return TaskNode(subject,
      variants,
      self.product_type,
      self.task_func,
      self.input_selects)

  @property
  def output_product_type(self):
    return self.product_type


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
    # Validate that
    # - all products selected by tasks are produced by some task or intrinsic, or come from a root
    #  subject type
    # - all goal products are also produced
    intrinsics = self._node_builder._intrinsics
    serializable_tasks = self._node_builder._tasks
    root_subject_types = self._root_subject_types
    task_and_intrinsic_product_types = set(serializable_tasks.keys())
    task_and_intrinsic_product_types.update(prd_t for sbj_t, prd_t in intrinsics.keys())

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
        # NB: We could also check goals of the Goal type to see if the products they request are also
        # available.
        raise ValueError('missing product for goal {} {}'.format(goal, goal_product))

    all_errors, all_warnings = self._check_task_selectors(serializable_tasks, type_collections)

    if all_warnings:
      logger.warn('warning count {}'.format(len(all_warnings)))
      logger.warn('Rules with warnings:\n  {}'.format('\n  '.join(all_warnings)))
    if all_errors:
      logger.error('err ct {}'.format(len(all_errors)))
      error_message = 'Invalid rules.\n  {}'.format('\n  '.join(all_errors))
      raise ValueError(error_message)

  def _check_task_selectors(self, serializable_tasks, type_collections):
    all_errors = []
    all_warnings = []
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
            err_msg, warn_msg = self._validate_product_is_provided(rule, select, selection_product,
              type_collections)
            if err_msg:
              rule_errors.append(err_msg)
            if warn_msg:
              rule_warnings.append(warn_msg)

        all_errors.extend(rule_errors)
        all_warnings.extend(rule_warnings)
    return all_errors, all_warnings

  def _validate_product_is_provided(self, rule, select, selection_product_type, type_collections):
    if any(selection_product_type in list_of_types for list_of_types in type_collections.values()):
      return None, None

    def superclass_of_selection(b):
      return issubclass(selection_product_type, b)

    def subclass_of_selection(b):
      return issubclass(b, selection_product_type)

    super_types_by_name = {name: filter(superclass_of_selection, types) for name, types in
      type_collections.items()}
    sub_types_by_name = {name: filter(subclass_of_selection, types) for name, types in
      type_collections.items()}

    if (all(len(b) == 0 for b in super_types_by_name.values()) and all(
        len(b) == 0 for b in sub_types_by_name.values())):
      # doesn't cover HasProducts relationships or projections since they have middle
      # implicit types
      err_msg = 'Rule entry with no possible fulfillment: {} There is no producer of {} ' \
                'or a super/subclass of ' \
                'it'.format(
        rule, select)
      return err_msg, None
    else:
      warn_msg = 'Rule entry fulfilled through indirect means {} '.format(select)
      for x in type_collections.keys():
        if super_types_by_name.get(x):
          warn_msg += '  has supertyped {} : {}'.format(x, super_types_by_name[x])
        if sub_types_by_name.get(x):
          warn_msg += '  has sub  typed {} : {}'.format(x, sub_types_by_name[x])
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
        serializable_tasks[output_type].add(
          TaskNodeFactory(tuple(input_selects), task, output_type)
        )
      else:
        raise Exception("Unexpected type for entry {}".format(entry))

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
      raise ValueError('Unrecognized Selector type "{}" for: {}'.format(selector_type, selector))


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
