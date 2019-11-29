# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
import inspect
import itertools
import sys
import typing
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from twitter.common.collections import OrderedSet

from pants.engine.goal import Goal
from pants.engine.selectors import Get
from pants.util.collections import assert_single_element
from pants.util.memo import memoized
from pants.util.meta import frozen_after_init


class _RuleVisitor(ast.NodeVisitor):
  """Pull `Get` calls out of an @rule body."""

  def __init__(self):
    super().__init__()
    self._gets: List[Get] = []

  @property
  def gets(self) -> List[Get]:
    return self._gets

  def _matches_get_name(self, node: ast.AST) -> bool:
    """Check if the node is a Name which matches 'Get'."""
    return isinstance(node, ast.Name) and node.id == Get.__name__

  def _is_get(self, node: ast.AST) -> bool:
    """Check if the node looks like a Get(...) or Get[X](...) call."""
    if isinstance(node, ast.Call):
      if self._matches_get_name(node.func):
        return True
      if isinstance(node.func, ast.Subscript) and self._matches_get_name(node.func.value):
        return True
      return False
    return False

  def visit_Call(self, node: ast.Call) -> None:
    if self._is_get(node):
      self._gets.append(Get.extract_constraints(node))
    # Ensure we descend into e.g. MultiGet(Get(...)...) calls.
    self.generic_visit(node)


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


def _get_starting_indent(source):
  """Used to remove leading indentation from `source` so ast.parse() doesn't raise an exception."""
  if source.startswith(" "):
    return sum(1 for _ in itertools.takewhile(lambda c: c in {' ', b' '}, source))
  return 0


def _make_rule(
  return_type: Type, parameter_types: typing.Iterable[Type], cacheable: bool = True,
  name: Optional[bool] = None
) -> Callable[[Callable], Callable]:
  """A @decorator that declares that a particular static function may be used as a TaskRule.

  As a special case, if the output_type is a subclass of `Goal`, the `Goal.Options` for the `Goal`
  are registered as dependency Optionables.

  :param return_type: The return/output type for the Rule. This must be a concrete Python type.
  :param parameter_types: A sequence of types that matches the number and order of arguments to the
                          decorated function.
  :param cacheable: Whether the results of executing the Rule should be cached as keyed by all of
                    its inputs.
  """

  is_goal_cls = issubclass(return_type, Goal)
  if is_goal_cls == cacheable:
    raise TypeError(
      'An `@rule` that produces a `Goal` must be declared with @console_rule in order to signal '
      'that it is not cacheable.'
    )

  def wrapper(func):
    if not inspect.isfunction(func):
      raise ValueError('The @rule decorator must be applied innermost of all decorators.')

    owning_module = sys.modules[func.__module__]
    source = inspect.getsource(func)
    beginning_indent = _get_starting_indent(source)
    if beginning_indent:
      source = "\n".join(line[beginning_indent:] for line in source.split("\n"))
    module_ast = ast.parse(source)

    def resolve_type(name):
      resolved = getattr(owning_module, name, None) or owning_module.__builtins__.get(name, None)
      if resolved is None:
        raise ValueError(
          f'Could not resolve type `{name}` in top level of module {owning_module.__name__}'
        )
      elif not isinstance(resolved, type):
        raise ValueError(
          f'Expected a `type` constructor for `{name}`, but got: {resolved} (type '
          f'`{type(resolved).__name__}`)'
        )
      return resolved

    gets = OrderedSet()
    rule_func_node = assert_single_element(
      node for node in ast.iter_child_nodes(module_ast)
      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func.__name__)

    parents_table = {}
    for parent in ast.walk(rule_func_node):
      for child in ast.iter_child_nodes(parent):
        parents_table[child] = parent

    rule_visitor = _RuleVisitor()
    rule_visitor.visit(rule_func_node)
    gets.update(
      Get.create_statically_for_rule_graph(resolve_type(p), resolve_type(s))
      for p, s in rule_visitor.gets)

    # Register dependencies for @console_rule/Goal.
    dependency_rules = (optionable_rule(return_type.subsystem_cls),) if is_goal_cls else None

    # Set a default name for Goal classes if one is not explicitly provided
    if is_goal_cls and name is None:
      effective_name = return_type.name
    else:
      effective_name = name

    func.rule = TaskRule(
        return_type,
        tuple(parameter_types),
        func,
        input_gets=tuple(gets),
        dependency_rules=dependency_rules,
        cacheable=cacheable,
        name=effective_name,
      )

    return func
  return wrapper


class InvalidTypeAnnotation(TypeError):
  """Indicates an incorrect type annotation for an `@rule`."""


class UnrecognizedRuleArgument(TypeError):
  """Indicates an unrecognized keyword argument to a `@rule`."""


class MissingTypeAnnotation(TypeError):
  """Indicates a missing type annotation for an `@rule`."""


class MissingReturnTypeAnnotation(InvalidTypeAnnotation):
  """Indicates a missing return type annotation for an `@rule`."""


class MissingParameterTypeAnnotation(InvalidTypeAnnotation):
  """Indicates a missing parameter type annotation for an `@rule`."""


def _ensure_type_annotation(
  annotation: Any, name: str, empty_value: Any, raise_type: Type[InvalidTypeAnnotation],
) -> type:
  if annotation == empty_value:
    raise raise_type(f'{name} is missing a type annotation.')
  if not isinstance(annotation, type):
    raise raise_type(f'The annotation for {name} must be a type, '
                     f'got {annotation} of type {type(annotation)}.')
  return annotation


PUBLIC_RULE_DECORATOR_ARGUMENTS = {'name'}
# We don't want @rule-writers to use 'cacheable' as a kwarg directly, but rather
# set it implicitly based on whether the rule annotation is @rule or @console_rule.
# So we leave it out of PUBLIC_RULE_DECORATOR_ARGUMENTS.
IMPLICIT_PRIVATE_RULE_DECORATOR_ARGUMENTS = {'cacheable'}


def rule_decorator(*args, **kwargs) -> Callable:
  if len(args) != 1 and not inspect.isfunction(args[0]):
    raise ValueError(
      'The @rule decorator expects no arguments and for the function it decorates to be '
      f'type-annotated. Given {args}.'
    )

  if len(set(kwargs) - PUBLIC_RULE_DECORATOR_ARGUMENTS - IMPLICIT_PRIVATE_RULE_DECORATOR_ARGUMENTS) != 0:
    raise UnrecognizedRuleArgument(
      f"`@rule`s and `@console_rule`s only accept the following keyword arguments: {PUBLIC_RULE_DECORATOR_ARGUMENTS}"
    )

  func = args[0]

  cacheable: bool = kwargs['cacheable']
  name = kwargs.get('name')

  signature = inspect.signature(func)
  func_id = f'@rule {func.__module__}:{func.__name__}'
  return_type = _ensure_type_annotation(
    annotation=signature.return_annotation,
    name=f'{func_id} return',
    empty_value=inspect.Signature.empty,
    raise_type=MissingReturnTypeAnnotation
  )
  parameter_types = tuple(
    _ensure_type_annotation(
      annotation=parameter.annotation,
      name=f'{func_id} parameter {name}',
      empty_value=inspect.Parameter.empty,
      raise_type=MissingParameterTypeAnnotation
    )
    for name, parameter in signature.parameters.items()
  )
  return _make_rule(return_type, parameter_types, cacheable=cacheable, name=name)(func)


def inner_rule(*args, **kwargs) -> Callable:
  if len(args) == 1 and inspect.isfunction(args[0]):
    return rule_decorator(*args, **kwargs)
  else:
    def wrapper(*args):
      return rule_decorator(*args, **kwargs)
    return wrapper


def rule(*args, **kwargs) -> Callable:
  return inner_rule(*args, **kwargs, cacheable=True)


def console_rule(*args, **kwargs) -> Callable:
  return inner_rule(*args, **kwargs, cacheable=False)


def union(cls):
  """A class decorator which other classes can specify that they can resolve to with `UnionRule`.

  Annotating a class with @union allows other classes to use a UnionRule() instance to indicate that
  they can be resolved to this base union class. This class will never be instantiated, and should
  have no members -- it is used as a tag only, and will be replaced with whatever object is passed
  in as the subject of a `await Get(...)`. See the following example:

  @union
  class UnionBase: pass

  @rule
  def get_some_union_type(x: X) -> B:
    result = await Get(ResultType, UnionBase, x.f())
    # ...

  If there exists a single path from (whatever type the expression `x.f()` returns) -> `ResultType`
  in the rule graph, the engine will retrieve and execute that path to produce a `ResultType` from
  `x.f()`. This requires also that whatever type `x.f()` returns was registered as a union member of
  `UnionBase` with a `UnionRule`.

  Unions allow @rule bodies to be written without knowledge of what types may eventually be provided
  as input -- rather, they let the engine check that there is a valid path to the desired result.
  """
  # TODO: Check that the union base type is used as a tag and nothing else (e.g. no attributes)!
  assert isinstance(cls, type)
  def non_member_error_message(subject):
    if hasattr(cls, 'non_member_error_message'):
      return cls.non_member_error_message(subject)
    desc = f' ("{cls.__doc__}")' if cls.__doc__ else ''
    return f'Type {type(subject).__name__} is not a member of the {cls.__name__} @union{desc}'

  return type(cls.__name__, (cls,), {
    '_is_union': True,
    'non_member_error_message': non_member_error_message,
  })


@dataclass(frozen=True)
class UnionRule:
  """Specify that an instance of `union_member` can be substituted wherever `union_base` is used."""
  union_base: Type
  union_member: Type

  def __post_init__(self) -> None:
    if not getattr(self.union_base, '_is_union', False):
      raise ValueError(
        f'union_base must be a type annotated with @union: was {self.union_base} '
        f'(type {type(self.union_base).__name__})'
      )


@dataclass(frozen=True)
class UnionMembership:
  union_rules: Dict[Type, typing.Iterable[type]]

  def is_member(self, union_type, putative_member):
    members = self.union_rules.get(union_type)
    if members is None:
      raise TypeError(f'Not a registered union type: {union_type}')
    return type(putative_member) in members


class Rule(ABC):
  """Rules declare how to produce products for the product graph.

  A rule describes what dependencies must be provided to produce a particular product. They also act
  as factories for constructing the nodes within the graph.
  """

  @property
  @abstractmethod
  def output_type(self):
    """An output `type` for the rule."""

  @property
  @abstractmethod
  def dependency_rules(self):
    """A tuple of @rules that are known to be necessary to run this rule.

    Note that installing @rules as flat lists is generally preferable, as Rules already implicitly
    form a loosely coupled RuleGraph: this facility exists only to assist with boilerplate removal.
    """

  @property
  @abstractmethod
  def dependency_optionables(self):
    """A tuple of Optionable classes that are known to be necessary to run this rule."""
    return ()


@frozen_after_init
@dataclass(unsafe_hash=True)
class TaskRule(Rule):
  """A Rule that runs a task function when all of its input selectors are satisfied.

  NB: This API is experimental, and not meant for direct consumption. To create a `TaskRule` you
  should always prefer the `@rule` constructor, and in cases where that is too constraining
  (likely due to #4535) please bump or open a ticket to explain the usecase.
  """
  _output_type: Type
  input_selectors: Tuple[Type, ...]
  input_gets: Tuple
  func: Callable
  _dependency_rules: Tuple
  _dependency_optionables: Tuple
  cacheable: bool
  name: Optional[str]

  def __init__(
    self,
    output_type: Type,
    input_selectors: Tuple[Type, ...],
    func: Callable,
    input_gets: Tuple,
    dependency_rules: Optional[Tuple] = None,
    dependency_optionables: Optional[Tuple] = None,
    cacheable: bool = True,
    name: Optional[str] = None,
  ):
    self._output_type = output_type
    self.input_selectors = input_selectors
    self.input_gets = input_gets
    self.func = func  # type: ignore[assignment] # cannot assign to a method
    self._dependency_rules = dependency_rules or ()
    self._dependency_optionables = dependency_optionables or ()
    self.cacheable = cacheable
    self.name = name

  def __str__(self):
    return ('(name={}, {}, {!r}, {}, gets={}, opts={})'
            .format(self.name or '<not defined>',
                    self.output_type.__name__,
                    self.input_selectors,
                    self.func.__name__,
                    self.input_gets,
                    self.dependency_optionables,
                    ))

  @property
  def output_type(self):
    return self._output_type

  @property
  def dependency_rules(self):
    return self._dependency_rules

  @property
  def dependency_optionables(self):
    return self._dependency_optionables


@frozen_after_init
@dataclass(unsafe_hash=True)
class RootRule(Rule):
  """Represents a root input to an execution of a rule graph.

  Roots act roughly like parameters, in that in some cases the only source of a
  particular type might be when a value is provided as a root subject at the beginning
  of an execution.
  """
  _output_type: Type

  def __init__(self, output_type: Type) -> None:
    self._output_type = output_type

  @property
  def output_type(self):
    return self._output_type

  @property
  def dependency_rules(self):
    return tuple()

  @property
  def dependency_optionables(self):
    return tuple()


# TODO: add typechecking here -- use dicts for `union_rules`.
@dataclass(frozen=True)
class RuleIndex:
  """Holds a normalized index of Rules used to instantiate Nodes."""
  rules: Any
  roots: Any
  union_rules: Any

  @classmethod
  def create(cls, rule_entries, union_rules=None):
    """Creates a RuleIndex with tasks indexed by their output type."""
    serializable_rules = OrderedDict()
    serializable_roots = OrderedSet()
    union_rules = OrderedDict(union_rules or ())

    def add_task(product_type, rule):
      # TODO(#7311): make a defaultdict-like wrapper for OrderedDict if more widely used.
      if product_type not in serializable_rules:
        serializable_rules[product_type] = OrderedSet()
      serializable_rules[product_type].add(rule)

    def add_root_rule(root_rule):
      serializable_roots.add(root_rule)

    def add_rule(rule):
      if isinstance(rule, RootRule):
        add_root_rule(rule)
      else:
        add_task(rule.output_type, rule)
      for dep_rule in rule.dependency_rules:
        add_rule(dep_rule)

    def add_type_transition_rule(union_rule):
      # NB: This does not require that union bases be supplied to `def rules():`, as the union type
      # is never instantiated!
      union_base = union_rule.union_base
      assert union_base._is_union
      union_member = union_rule.union_member
      if union_base not in union_rules:
        union_rules[union_base] = OrderedSet()
      union_rules[union_base].add(union_member)

    for entry in rule_entries:
      if isinstance(entry, Rule):
        add_rule(entry)
      elif isinstance(entry, UnionRule):
        add_type_transition_rule(entry)
      elif hasattr(entry, '__call__'):
        rule = getattr(entry, 'rule', None)
        if rule is None:
          raise TypeError("Expected callable {} to be decorated with @rule.".format(entry))
        add_rule(rule)
      else:
        raise TypeError("""\
Rule entry {} had an unexpected type: {}. Rules either extend Rule or UnionRule, or are static \
functions decorated with @rule.""".format(entry, type(entry)))

    return cls(serializable_rules, serializable_roots, union_rules)

  @dataclass(frozen=True)
  class NormalizedRules:
    rules: Any
    union_rules: Any

  def normalized_rules(self):
    rules = OrderedSet(rule
                       for ruleset in self.rules.values()
                       for rule in ruleset)
    rules.update(self.roots)
    return self.NormalizedRules(rules, self.union_rules)
