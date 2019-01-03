# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast
import functools
import inspect
import itertools
import logging
import sys
from abc import abstractproperty
from builtins import bytes, str
from collections import Iterable, OrderedDict
from types import GeneratorType

from future.utils import PY2
from twitter.common.collections import OrderedSet

from pants.engine.selectors import Get, type_or_constraint_repr
from pants.util.collections import assert_single_element
from pants.util.memo import memoized
from pants.util.meta import AbstractClass
from pants.util.objects import Exactly, datatype


logger = logging.getLogger(__name__)


class _RuleVisitor(ast.NodeVisitor):
  """Pull `Get` calls out of an @rule body and validate `yield` statements."""

  def __init__(self, func, frame, parents_table, siblings_table):
    super(_RuleVisitor, self).__init__()
    self.gets = []
    self._func = func
    self._frame = frame
    self._parents_table = parents_table
    self._siblings_table = siblings_table
    self._yields_in_assignments = set()

  def visit_Call(self, node):
    if isinstance(node.func, ast.Name) and node.func.id == Get.__name__:
      self.gets.append(Get.extract_constraints(node))

  def visit_Assign(self, node):
    if isinstance(node.value, ast.Yield):
      self._yields_in_assignments.add(node.value)
    self.generic_visit(node)

  class YieldVisitError(Exception):
    def __init__(self, node, func, frame, msg, *args, **kwargs):
      filename, line_number, _, context_lines, _ = inspect.getframeinfo(frame, context=4)
      err_msg = ("""\
In function {func_name}: {msg}
{filename}:{line_number}:
{context_lines}

The invalid `yield` statement (in the body of the above function) was: {node}
""".format(func_name=func.__name__, msg=msg,
           filename=filename, line_number=line_number,
           context_lines=''.join(context_lines).strip(),
           node=ast.dump(node)))
      super(_RuleVisitor.YieldVisitError, self).__init__(err_msg, *args, **kwargs)

  def _maybe_end_of_stmt_list(self, attr_value):
    # 'body' is also used in Exec for some reason, but as a single expr, so we check if the value is
    # iterable.
    if (attr_value is not None) and isinstance(attr_value, Iterable):
      result = list(attr_value)
      if len(result) > 0:
        return result[-1]
    return None

  def _stmt_is_at_end_of_parent_list(self, stmt):
    # See https://docs.python.org/2/library/ast.html#abstract-grammar. 'body', 'orelse', and
    # 'finalbody' are the only attributes which can contain lists of stmts.
    parent_stmt = self._parents_table[stmt]
    last_body_stmt = self._maybe_end_of_stmt_list(getattr(parent_stmt, 'body', None))
    if stmt == last_body_stmt:
      return True
    last_orelse_stmt = self._maybe_end_of_stmt_list(getattr(parent_stmt, 'orelse', None))
    if stmt == last_orelse_stmt:
      return True
    last_finally_stmt = self._maybe_end_of_stmt_list(getattr(parent_stmt, 'finalbody', None))
    if stmt == last_finally_stmt:
      return True
    return False

  def visit_Yield(self, node):
    # A yield outside of an assignment is only allowed to be immediately preceding a final `return`.
    if node in self._yields_in_assignments:
      self.generic_visit(node)
    else:
      # Get the position of the current yield (which is part of an Expr stmt).
      expr_for_yield = self._parents_table[node]

      if not self._stmt_is_at_end_of_parent_list(expr_for_yield):
        raise self.YieldVisitError(
          node, self._func, self._frame,
          """\
A yield in an @rule without an assignment is equivalent to a return, and we
currently require that it comes at the end of a series of statements.
Use `_ = yield Get(...)` if you wish to yield control to the engine and discard the result.
""")



class _GoalProduct(object):
  """GoalProduct is a factory for anonymous singleton types representing the execution of goals.

  The created types are returned by `@console_rule` instances, which may not have any outputs
  of their own.
  """
  PRODUCT_MAP = {}

  @staticmethod
  def _synthesize_goal_product(name):
    product_type_name = '{}GoalExecution'.format(name.capitalize())
    if PY2:
      product_type_name = product_type_name.encode('utf-8')
    return type(product_type_name, (datatype([]),), {})

  @classmethod
  def for_name(cls, name):
    assert isinstance(name, (bytes, str))
    if name is bytes:
      name = name.decode('utf-8')
    if name not in cls.PRODUCT_MAP:
      cls.PRODUCT_MAP[name] = cls._synthesize_goal_product(name)
    return cls.PRODUCT_MAP[name]


def _terminated(generator, terminator):
  """A generator that "appends" the given terminator value to the given generator."""
  gen_input = None
  try:
    while True:
      res = generator.send(gen_input)
      gen_input = yield res
  except StopIteration:
    yield terminator


@memoized
def optionable_rule(optionable_factory):
  """Returns a TaskRule that constructs an instance of the Optionable for the given OptionableFactory.

  TODO: This API is slightly awkward for two reasons:
    1) We should consider whether Subsystems/Optionables should be constructed explicitly using
      `@rule`s, which would allow them to have non-option dependencies that would be explicit in
      their constructors (which would avoid the need for the `Subsystem.Factory` pattern).
    2) Optionable depending on TaskRule would create a cycle in the Python package graph.
  """
  return TaskRule(**optionable_factory.signature())


def _make_rule(output_type, input_selectors, for_goal=None, cacheable=True):
  """A @decorator that declares that a particular static function may be used as a TaskRule.

  :param Constraint output_type: The return/output type for the Rule. This may be either a
    concrete Python type, or an instance of `Exactly` representing a union of multiple types.
  :param list input_selectors: A list of Selector instances that matches the number of arguments
    to the @decorated function.
  :param str for_goal: If this is a @console_rule, which goal string it's called for.
  """

  def wrapper(func):
    if not inspect.isfunction(func):
      raise ValueError('The @rule decorator must be applied innermost of all decorators.')

    caller_frame = inspect.stack()[1][0]
    source = inspect.getsource(func)
    if source.startswith(" "):
      to_trim = sum(1 for _ in itertools.takewhile(lambda c: c in {' ', b' '}, source))
      source = "\n".join(line[to_trim:] for line in source.split("\n"))
    module_ast = ast.parse(source)

    def resolve_type(name):
      resolved = caller_frame.f_globals.get(name) or caller_frame.f_builtins.get(name)
      if not isinstance(resolved, (type, Exactly)):
        # TODO: should this say "...or Exactly instance;"?
        raise ValueError('Expected either a `type` constructor or TypeConstraint instance; '
                         'got: {}'.format(name))
      return resolved

    gets = OrderedSet()
    rule_func_node = assert_single_element(
      node for node in ast.iter_child_nodes(module_ast)
      if isinstance(node, ast.FunctionDef) and node.name == func.__name__
    )

    siblings_table = {}
    parents_table = {}
    for parent in ast.walk(rule_func_node):
      children_ordered = []
      for child in ast.iter_child_nodes(parent):
        parents_table[child] = parent
        children_ordered.append(child)
      siblings_table[parent] = children_ordered

    rule_visitor = _RuleVisitor(func, caller_frame, parents_table, siblings_table)
    rule_visitor.visit(rule_func_node)
    gets.update(Get(resolve_type(p), resolve_type(s)) for p, s in rule_visitor.gets)

    # For @console_rule, redefine the function to avoid needing a literal return of the output type.
    if for_goal:
      def goal_and_return(*args, **kwargs):
        res = func(*args, **kwargs)
        if isinstance(res, GeneratorType):
          # Return a generator with an output_type instance appended.
          return _terminated(res, output_type())
        elif res is not None:
          raise Exception('A @console_rule should not have a return value.')
        return output_type()
      functools.update_wrapper(goal_and_return, func)
      wrapped_func = goal_and_return
    else:
      wrapped_func = func

    wrapped_func.rule = TaskRule(
        output_type,
        tuple(input_selectors),
        wrapped_func,
        input_gets=tuple(gets),
        goal=for_goal,
        cacheable=cacheable
      )

    return wrapped_func
  return wrapper


def rule(output_type, input_selectors):
  return _make_rule(output_type, input_selectors)


def console_rule(goal_name, input_selectors):
  output_type = _GoalProduct.for_name(goal_name)
  return _make_rule(output_type, input_selectors, goal_name, False)


class Rule(AbstractClass):
  """Rules declare how to produce products for the product graph.

  A rule describes what dependencies must be provided to produce a particular product. They also act
  as factories for constructing the nodes within the graph.
  """

  @abstractproperty
  def output_constraint(self):
    """An output Constraint type for the rule."""

  @abstractproperty
  def dependency_optionables(self):
    """A tuple of Optionable classes that are known to be necessary to run this rule."""


class TaskRule(datatype([
  'output_constraint',
  ('input_selectors', tuple),
  ('input_gets', tuple),
  'func',
  'goal',
  ('dependency_optionables', tuple),
  ('cacheable', bool),
]), Rule):
  """A Rule that runs a task function when all of its input selectors are satisfied.

  NB: This API is experimental, and not meant for direct consumption. To create a `TaskRule` you
  should always prefer the `@rule` constructor, and in cases where that is too constraining
  (likely due to #4535) please bump or open a ticket to explain the usecase.
  """

  def __new__(cls,
              output_type,
              input_selectors,
              func,
              input_gets,
              goal=None,
              dependency_optionables=None,
              cacheable=True):
    # Validate result type.
    if isinstance(output_type, Exactly):
      constraint = output_type
    elif isinstance(output_type, type):
      constraint = Exactly(output_type)
    else:
      raise TypeError("Expected an output_type for rule `{}`, got: {}".format(
        func.__name__, output_type))

    return super(TaskRule, cls).__new__(
        cls,
        constraint,
        input_selectors,
        input_gets,
        func,
        goal,
        dependency_optionables or tuple(),
        cacheable,
      )

  def __str__(self):
    return '({}, {!r}, {})'.format(type_or_constraint_repr(self.output_constraint),
                                   self.input_selectors,
                                   self.func.__name__)


class SingletonRule(datatype(['output_constraint', 'value']), Rule):
  """A default rule for a product, which is thus a singleton for that product."""

  @classmethod
  def from_instance(cls, obj):
    return cls(type(obj), obj)

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
  def dependency_optionables(self):
    return tuple()

  def __repr__(self):
    return '{}({}, {})'.format(type(self).__name__, type_or_constraint_repr(self.output_constraint), self.value)


class RootRule(datatype(['output_constraint']), Rule):
  """Represents a root input to an execution of a rule graph.

  Roots act roughly like parameters, in that in some cases the only source of a
  particular type might be when a value is provided as a root subject at the beginning
  of an execution.
  """

  @property
  def dependency_optionables(self):
    return tuple()


class RuleIndex(datatype(['rules', 'roots'])):
  """Holds a normalized index of Rules used to instantiate Nodes."""

  @classmethod
  def create(cls, rule_entries):
    """Creates a RuleIndex with tasks indexed by their output type."""
    serializable_rules = OrderedDict()
    serializable_roots = OrderedSet()

    def add_task(product_type, rule):
      if product_type not in serializable_rules:
        serializable_rules[product_type] = OrderedSet()
      serializable_rules[product_type].add(rule)

    def add_rule(rule):
      if isinstance(rule, RootRule):
        serializable_roots.add(rule)
        return
      # TODO: Ensure that interior types work by indexing on the list of types in
      # the constraint. This heterogenity has some confusing implications:
      #   see https://github.com/pantsbuild/pants/issues/4005
      for kind in rule.output_constraint.types:
        add_task(kind, rule)
      add_task(rule.output_constraint, rule)

    for entry in rule_entries:
      if isinstance(entry, Rule):
        add_rule(entry)
      elif hasattr(entry, '__call__'):
        rule = getattr(entry, 'rule', None)
        if rule is None:
          raise TypeError("Expected callable {} to be decorated with @rule.".format(entry))
        add_rule(rule)
      else:
        raise TypeError("Unexpected rule type: {}. "
                        "Rules either extend Rule, or are static functions "
                        "decorated with @rule.".format(type(entry)))

    return cls(serializable_rules, serializable_roots)

  def normalized_rules(self):
    rules = OrderedSet(rule
                       for ruleset in self.rules.values()
                       for rule in ruleset)
    rules.update(self.roots)
    return rules
