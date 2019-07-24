# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
import inspect
import itertools
import logging
import sys
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Iterable

import asttokens
from twitter.common.collections import OrderedSet

from pants.engine.goal import Goal
from pants.engine.selectors import Get
from pants.util.collections import assert_single_element
from pants.util.memo import memoized
from pants.util.objects import SubclassesOf, TypedCollection, datatype


logger = logging.getLogger(__name__)


_type_field = SubclassesOf(type)


class _RuleVisitor(ast.NodeVisitor):
  """Pull `Get` calls out of an @rule body and validate `yield` statements."""

  def __init__(self, func, func_node, func_source, orig_indent, parents_table):
    super().__init__()
    self._gets = []
    self._func = func
    self._func_node = func_node
    self._func_source = func_source
    self._orig_indent = orig_indent
    self._parents_table = parents_table
    self._yields_in_assignments = set()

  @property
  def gets(self):
    return self._gets

  def _generate_ast_error_message(self, node, msg):
    # This is the location info of the start of the decorated @rule.
    filename = inspect.getsourcefile(self._func)
    source_lines, line_number = inspect.getsourcelines(self._func)

    # The asttokens library is able to keep track of line numbers and column offsets for us -- the
    # stdlib ast library only provides these relative to each parent node.
    tokenized_rule_body = asttokens.ASTTokens(self._func_source,
                                              tree=self._func_node,
                                              filename=filename)
    start_offset, _ = tokenized_rule_body.get_text_range(node)
    line_offset, col_offset = asttokens.LineNumbers(self._func_source).offset_to_line(start_offset)
    node_file_line = line_number + line_offset - 1
    # asttokens also very helpfully lets us provide the exact text of the node we want to highlight
    # in an error message.
    node_text = tokenized_rule_body.get_text(node)

    fully_indented_node_col = col_offset + self._orig_indent
    indented_node_text = '{}{}'.format(
      # The node text doesn't have any initial whitespace, so we have to add it back.
      col_offset * ' ',
      '\n'.join(
        # We removed the indentation from the original source in order to parse it with the ast
        # library (otherwise it raises an exception), so we add it back here.
        '{}{}'.format(self._orig_indent * ' ', l)
        for l in node_text.split('\n')))

    return ("""In function {func_name}: {msg}
The invalid statement was:
{filename}:{node_line_number}:{node_col}
{node_text}

The rule defined by function `{func_name}` begins at:
{filename}:{line_number}:{orig_indent}
{source_lines}
""".format(func_name=self._func.__name__, msg=msg,
           filename=filename, line_number=line_number, orig_indent=self._orig_indent,
           node_line_number=node_file_line,
           node_col=fully_indented_node_col,
           node_text=indented_node_text,
           # Strip any leading or trailing newlines from the start of the rule body.
           source_lines=''.join(source_lines).strip('\n')))

  class YieldVisitError(Exception): pass

  @staticmethod
  def _maybe_end_of_stmt_list(attr_value):
    """If `attr_value` is a non-empty iterable, return its final element."""
    if (attr_value is not None) and isinstance(attr_value, Iterable):
      result = list(attr_value)
      if len(result) > 0:
        return result[-1]
    return None

  def _stmt_is_at_end_of_parent_list(self, stmt):
    """Determine if `stmt` is at the end of a list of statements (i.e. can be an implicit `return`).

    If there are any statements following `stmt` at the same level of nesting, this method returns
    False, such as the following (if `stmt` is the Expr for `yield 'good'`):

    if 2 + 2 == 5:
      yield 'good'
      a = 3

    Note that this returns False even if the statement following `stmt` is a `return`.

    However, if `stmt` is at the end of a list of statements, it can be made more clear that `stmt`
    is intended to represent a `return`. Another way to view this method is as a dead code
    elimination check, for a `stmt` which is intended to represent control flow moving out of the
    current @rule. For example, this method would return True for both of the yield Expr statements
    in the below snippet.

    if True:
      yield 3
    else:
      a = 3
      yield a

    This checking is performed by getting the parent of `stmt` with a pre-generated table passed
    into the constructor.

    See https://docs.python.org/2/library/ast.html#abstract-grammar for the grammar specification.
    'body', 'orelse', and 'finalbody' are the only attributes on any AST nodes which can contain
    lists of stmts.  'body' is also an attribute in the Exec statement for some reason, but as a
    single expr, so we simply check if it is iterable in `_maybe_end_of_stmt_list()`.
    """
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

  def visit_Call(self, node):
    if isinstance(node.func, ast.Name) and node.func.id == Get.__name__:
      self._gets.append(Get.extract_constraints(node))

  def visit_Assign(self, node):
    if isinstance(node.value, ast.Yield):
      self._yields_in_assignments.add(node.value)
    self.generic_visit(node)

  def visit_Yield(self, node):
    if node in self._yields_in_assignments:
      self.generic_visit(node)
    else:
      # The current yield "expr" is the child of an "Expr" "stmt".
      expr_for_yield = self._parents_table[node]

      if not self._stmt_is_at_end_of_parent_list(expr_for_yield):
        raise self.YieldVisitError(
          self._generate_ast_error_message(node, """\
yield in @rule without assignment must come at the end of a series of statements.

A yield in an @rule without an assignment is equivalent to a return, and we
currently require that no statements follow such a yield at the same level of nesting.
Use `_ = yield Get(...)` if you wish to yield control to the engine and discard the result.
"""))


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
  """Remove leading indentation from `source` so ast.parse() doesn't raise an exception."""
  if source.startswith(" "):
    return sum(1 for _ in itertools.takewhile(lambda c: c in {' ', b' '}, source))
  return 0


def _make_rule(output_type, input_selectors, cacheable=True):
  """A @decorator that declares that a particular static function may be used as a TaskRule.

  As a special case, if the output_type is a subclass of `Goal`, the `Goal.Options` for the `Goal`
  are registered as dependency Optionables.

  :param type output_type: The return/output type for the Rule. This must be a concrete Python type.
  :param list input_selectors: A list of Selector instances that matches the number of arguments
    to the @decorated function.
  """

  is_goal_cls = isinstance(output_type, type) and issubclass(output_type, Goal)
  if is_goal_cls == cacheable:
    raise TypeError('An `@rule` that produces a `Goal` must be declared with @console_rule in order '
                    'to signal that it is not cacheable.')

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
          f'Expected a `type` constructor for `{name}`, but got: {resolved} (type `{type(resolved).__name__}`)'
        )
      return resolved

    gets = OrderedSet()
    rule_func_node = assert_single_element(
      node for node in ast.iter_child_nodes(module_ast)
      if isinstance(node, ast.FunctionDef) and node.name == func.__name__)

    parents_table = {}
    for parent in ast.walk(rule_func_node):
      for child in ast.iter_child_nodes(parent):
        parents_table[child] = parent

    rule_visitor = _RuleVisitor(
      func=func,
      func_node=rule_func_node,
      func_source=source,
      orig_indent=beginning_indent,
      parents_table=parents_table,
    )
    rule_visitor.visit(rule_func_node)
    gets.update(
      Get.create_statically_for_rule_graph(resolve_type(p), resolve_type(s))
      for p, s in rule_visitor.gets)

    # Register dependencies for @console_rule/Goal.
    if is_goal_cls:
      dependency_rules = (optionable_rule(output_type.Options),)
    else:
      dependency_rules = None

    func.rule = TaskRule(
        output_type,
        tuple(input_selectors),
        func,
        input_gets=tuple(gets),
        dependency_rules=dependency_rules,
        cacheable=cacheable,
      )

    return func
  return wrapper


def rule(output_type, input_selectors):
  return _make_rule(output_type, input_selectors)


def console_rule(goal_cls, input_selectors):
  return _make_rule(goal_cls, input_selectors, False)


def union(cls):
  """A class decorator which other classes can specify that they can resolve to with `UnionRule`.

  Annotating a class with @union allows other classes to use a UnionRule() instance to indicate that
  they can be resolved to this base union class. This class will never be instantiated, and should
  have no members -- it is used as a tag only, and will be replaced with whatever object is passed
  in as the subject of a `yield Get(...)`. See the following example:

  @union
  class UnionBase: pass

  @rule(B, [X])
  def get_some_union_type(x):
    result = yield Get(ResultType, UnionBase, x.f())
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
  if cls.__doc__:
    union_description = cls.__doc__
  else:
    union_description = cls.__name__

  return type(cls.__name__, (cls,), {
    '_is_union': True,
    'union_description': union_description,
  })


class UnionRule(datatype([
    ('union_base', _type_field),
    ('union_member', _type_field),
])):
  """Specify that an instance of `union_member` can be substituted wherever `union_base` is used."""

  def __new__(cls, union_base, union_member):
    if not getattr(union_base, '_is_union', False):
      raise cls.make_type_error('union_base must be a type annotated with @union: was {} (type {})'
                                .format(union_base, type(union_base).__name__))
    return super().__new__(cls, union_base, union_member)


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


class TaskRule(datatype([
  ('output_type', _type_field),
  ('input_selectors', TypedCollection(SubclassesOf(type))),
  ('input_gets', tuple),
  'func',
  ('dependency_rules', tuple),
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
              dependency_optionables=None,
              dependency_rules=None,
              cacheable=True):

    # Create.
    return super().__new__(
        cls,
        output_type,
        input_selectors,
        input_gets,
        func,
        dependency_rules or tuple(),
        dependency_optionables or tuple(),
        cacheable,
      )

  def __str__(self):
    return ('({}, {!r}, {}, gets={}, opts={})'
            .format(self.output_type.__name__,
                    self.input_selectors,
                    self.func.__name__,
                    self.input_gets,
                    self.dependency_optionables))


class RootRule(datatype([('output_type', _type_field)]), Rule):
  """Represents a root input to an execution of a rule graph.

  Roots act roughly like parameters, in that in some cases the only source of a
  particular type might be when a value is provided as a root subject at the beginning
  of an execution.
  """

  @property
  def dependency_rules(self):
    return tuple()

  @property
  def dependency_optionables(self):
    return tuple()


# TODO: add typechecking here -- would need to have a TypedCollection for dicts for `union_rules`.
class RuleIndex(datatype(['rules', 'roots', 'union_rules'])):
  """Holds a normalized index of Rules used to instantiate Nodes."""

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

  class NormalizedRules(datatype(['rules', 'union_rules'])): pass

  def normalized_rules(self):
    rules = OrderedSet(rule
                       for ruleset in self.rules.values()
                       for rule in ruleset)
    rules.update(self.roots)
    return self.NormalizedRules(rules, self.union_rules)
