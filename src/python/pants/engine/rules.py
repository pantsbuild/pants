# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
import inspect
import logging
from abc import abstractproperty
from collections import OrderedDict
from types import TypeType

from twitter.common.collections import OrderedSet

from pants.engine.selectors import Get, type_or_constraint_repr
from pants.util.meta import AbstractClass
from pants.util.objects import Exactly, datatype


logger = logging.getLogger(__name__)


class _RuleVisitor(ast.NodeVisitor):
  def __init__(self):
    super(_RuleVisitor, self).__init__()
    self.gets = []

  def visit_Call(self, node):
    if not isinstance(node.func, ast.Name) or node.func.id != Get.__name__:
      return
    self.gets.append(Get.extract_constraints(node))


def rule(output_type, input_selectors):
  """A @decorator that declares that a particular static function may be used as a TaskRule.

  :param Constraint output_type: The return/output type for the Rule. This may be either a
    concrete Python type, or an instance of `Exactly` representing a union of multiple types.
  :param list input_selectors: A list of Selector instances that matches the number of arguments
    to the @decorated function.
  """

  def wrapper(func):
    if not inspect.isfunction(func):
      raise ValueError('The @rule decorator must be applied innermost of all decorators.')

    caller_frame = inspect.stack()[1][0]
    module_ast = ast.parse(inspect.getsource(func))

    def resolve_type(name):
      resolved = caller_frame.f_globals.get(name) or caller_frame.f_builtins.get(name)
      if not isinstance(resolved, (TypeType, Exactly)):
        # TODO(cosmicexplorer): should this say "...or Exactly instance;"?
        raise ValueError('Expected either a `type` constructor or TypeConstraint instance; '
                         'got: {}'.format(name))
      return resolved

    gets = OrderedSet()
    for node in ast.iter_child_nodes(module_ast):
      if isinstance(node, ast.FunctionDef) and node.name == func.__name__:
        rule_visitor = _RuleVisitor()
        rule_visitor.visit(node)
        gets.update(Get(resolve_type(p), resolve_type(s)) for p, s in rule_visitor.gets)

    func._rule = TaskRule(output_type, input_selectors, func, input_gets=list(gets))
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


class TaskRule(datatype(['output_constraint', 'input_selectors', 'input_gets', 'func']), Rule):
  """A Rule that runs a task function when all of its input selectors are satisfied.

  TODO: Make input_gets non-optional when more/all rules are using them.
  """

  def __new__(cls, output_type, input_selectors, func, input_gets=None):
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

    # Validate gets.
    input_gets = [] if input_gets is None else input_gets
    if not isinstance(input_gets, list):
      raise TypeError("Expected a list of Gets for rule `{}`, got: {}".format(
        func.__name__, type(input_gets)))

    # Create.
    return super(TaskRule, cls).__new__(cls, constraint, tuple(input_selectors), tuple(input_gets), func)

  def __str__(self):
    return '({}, {!r}, {})'.format(type_or_constraint_repr(self.output_constraint),
                                   self.input_selectors,
                                   self.func.__name__)


class SingletonRule(datatype(['output_constraint', 'value']), Rule):
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


class RootRule(datatype(['output_constraint']), Rule):
  """Represents a root input to an execution of a rule graph.

  Roots act roughly like parameters, in that in some cases the only source of a
  particular type might be when a value is provided as a root subject at the beginning
  of an execution.
  """

  def input_selectors(self):
    return []


class RuleIndex(datatype(['rules', 'roots'])):
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
        # NB Ensure that interior types from SelectDependencies work by
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
