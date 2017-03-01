# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from abc import abstractproperty
from collections import OrderedDict

from twitter.common.collections import OrderedSet

from pants.engine.addressable import Exactly
from pants.engine.selectors import type_or_constraint_repr
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
    """Collection of input selectors"""

  @abstractproperty
  def func(self):
    """Rule function."""

  @abstractproperty
  def output_product_type(self):
    """The product type produced by this rule."""

  def as_triple(self):
    """Constructs an (output, input, func) triple for this rule."""
    return (self.output_product_type, self.input_selectors, self.func)


class TaskRule(datatype('TaskRule', ['input_selectors', 'func', 'product_type', 'constraint']),
               Rule):
  """A Rule that runs a task function when all of its input selectors are satisfied."""

  @property
  def output_product_type(self):
    return self.product_type

  def __str__(self):
    return '({}, {!r}, {})'.format(type_or_constraint_repr(self.product_type),
                                   self.input_selectors,
                                   self.func.__name__)


class SingletonRule(datatype('SingletonRule', ['product_type', 'func']), Rule):
  """A default rule for a product, which is thus a singleton for that product."""

  @property
  def input_selectors(self):
    return tuple()

  @property
  def output_product_type(self):
    return self.product_type

  def __repr__(self):
    return '{}({}, {})'.format(type(self).__name__,
                               self.product_type.__name__,
                               self.func.__name__)


class IntrinsicRule(datatype('IntrinsicRule', ['subject_type', 'product_type', 'func']), Rule):
  """A default rule for a pair of subject+product."""

  @property
  def input_selectors(self):
    return tuple()

  @property
  def output_product_type(self):
    return self.product_type

  def __repr__(self):
    return '{}(({}, {}), {})'.format(type(self).__name__,
                                     self.subject_type.__name__,
                                     self.output_product_type.__name__,
                                     self.func.__name__)


class RuleIndex(datatype('RuleIndex', ['tasks', 'intrinsics', 'singletons'])):
  """Holds an index of tasks and intrinsics used to instantiate Nodes."""

  @classmethod
  def create(cls, task_entries, intrinsic_entries=None, singleton_entries=None):
    """Creates a NodeBuilder with tasks indexed by their output type."""
    intrinsic_entries = intrinsic_entries or tuple()
    singleton_entries = singleton_entries or tuple()
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
        # TODO: The heterogenity here has some confusing implications here:
        # see https://github.com/pantsbuild/pants/issues/4005
        for kind in constraint.types:
          # NB Ensure that interior types from SelectDependencies / SelectProjections work by
          # indexing on the list of types in the constraint.
          add_task(kind, factory)
        add_task(constraint, factory)
      else:
        raise TypeError("Unexpected rule type: {}."
                        " Rules either extend Rule, or are 3 elem tuples.".format(type(entry)))

    intrinsics = dict()
    for output_type, input_type, func in intrinsic_entries:
      key = (input_type, output_type)
      if key in intrinsics:
        raise ValueError('intrinsic provided by {} has already been provided by: {}'.format(
          func.__name__, intrinsics[key]))
      intrinsics[key] = IntrinsicRule(input_type, output_type, func)

    singletons = dict()
    for output_type, func in singleton_entries:
      if output_type in singletons:
        raise ValueError('singleton provided by {} has already been provided by: {}'.format(
          func.__name__, singletons[output_type]))
      singletons[output_type] = SingletonRule(output_type, func)
    return cls(serializable_tasks, intrinsics, singletons)