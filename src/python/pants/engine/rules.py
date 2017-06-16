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


def rule(output_type, input_selectors):
  """A @decorator that declares that a particular static function may be used as a TaskRule.

  :param Constraint output_type: The return/output type for the Rule. This may be either a
    concrete Python type, or an instance of `Exactly` representing a union of multiple types.
  :param list input_selectors: A list of Selector instances that matches the number of arguments
    to the @decorated function.
  """
  def wrapper(func):
    func._rule = TaskRule(output_type, input_selectors, func)
    return func
  return wrapper


class Rule(AbstractClass):
  """Rules declare how to produce products for the product graph.

  A rule describes what dependencies must be provided to produce a particular product. They also act
  as factories for constructing the nodes within the graph.
  """

  @abstractproperty
  def output_constraint(self):
    """An output Constraint type for the rule."""

  @abstractproperty
  def input_selectors(self):
    """Collection of input selectors."""


class TaskRule(datatype('TaskRule', ['output_constraint', 'input_selectors', 'func']), Rule):
  """A Rule that runs a task function when all of its input selectors are satisfied."""

  def __new__(cls, output_type, input_selectors, func):
    # Validate result type.
    if isinstance(output_type, Exactly):
      constraint = output_type
    elif isinstance(output_type, type):
      constraint = Exactly(output_type)
    else:
      raise TypeError("Expected an output_type for rule `{}`, got: {}".format(
        func.__name__, output_type))

    # Validate selectors.
    if not isinstance(input_selectors, list):
      raise TypeError("Expected a list of Selectors for rule `{}`, got: {}".format(
        func.__name__, type(input_selectors)))

    # Create.
    return super(TaskRule, cls).__new__(cls, constraint, tuple(input_selectors), func)

  def __str__(self):
    return '({}, {!r}, {})'.format(type_or_constraint_repr(self.output_constraint),
                                   self.input_selectors,
                                   self.func.__name__)


class SingletonRule(datatype('SingletonRule', ['output_constraint', 'value']), Rule):
  """A default rule for a product, which is thus a singleton for that product."""

  def __new__(cls, output_type, value):
    # Validate result type.
    if isinstance(output_type, Exactly):
      constraint = output_type
    elif isinstance(output_type, type):
      constraint = Exactly(output_type)
    else:
      raise TypeError("Expected an output_type for rule; got: {}".format(output_type))

    # Create.
    return super(SingletonRule, cls).__new__(cls, constraint, value)

  @property
  def input_selectors(self):
    return tuple()

  def __repr__(self):
    return '{}({}, {})'.format(type(self).__name__, type_or_constraint_repr(self.output_constraint), self.value)


class RootRule(datatype('RootRule', ['output_constraint']), Rule):
  """Represents a root input to an execution of a rule graph.
  
  Roots act roughly like parameters, in that in some cases the only source of a
  particular type might be when a value is provided as a root subject at the beginning
  of an execution.
  """

  def input_selectors(self):
    return []


class RuleIndex(datatype('RuleIndex', ['rules', 'roots'])):
  """Holds an index of Tasks and Singletons used to instantiate Nodes."""

  @classmethod
  def create(cls, rule_entries):
    """Creates a NodeBuilder with tasks indexed by their output type."""
    # NB make tasks ordered so that gen ordering is deterministic.
    serializable_rules = OrderedDict()
    serializable_roots = set()

    def add_task(product_type, rule):
      if product_type not in serializable_rules:
        serializable_rules[product_type] = OrderedSet()
      serializable_rules[product_type].add(rule)

    def add_rule(rule):
      if isinstance(rule, RootRule):
        serializable_roots.add(rule.output_constraint)
        return
      # TODO: The heterogenity here has some confusing implications here:
      # see https://github.com/pantsbuild/pants/issues/4005
      for kind in rule.output_constraint.types:
        # NB Ensure that interior types from SelectDependencies / SelectProjections work by
        # indexing on the list of types in the constraint.
        add_task(kind, rule)
      add_task(rule.output_constraint, rule)

    for entry in rule_entries:
      if isinstance(entry, Rule):
        add_rule(entry)
      elif hasattr(entry, '__call__'):
        rule = getattr(entry, '_rule', None)
        if rule is None:
          raise TypeError("Expected callable {} to be decorated with @rule.".format(entry))
        add_rule(rule)
      else:
        raise TypeError("Unexpected rule type: {}. "
                        "Rules either extend Rule, or are static functions "
                        "decorated with @rule.".format(type(entry)))

    return cls(serializable_rules, serializable_roots)
