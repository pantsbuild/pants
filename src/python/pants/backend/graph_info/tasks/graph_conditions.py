# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re


class GraphCondition(object):
  """Base class for a predicate that acts on a task context and a target."""

  def accept(self, context, target):
    """Tests this condition against the given target.

    :param context: The task's context object.
    :param target: The target to test this condition against.
    :returns: True or False.
    """
    raise NotImplementedError()

  def __call__(self, context, target):
    """This is just for convenience, delegating to `accept`, allowing for function-like syntax."""
    return self.accept(context, target)


class MetaCondition(GraphCondition):
  """Base class for conditions with operate on other conditions."""

  @property
  def subconditions(self):
    raise NotImplementedError()

  def __iter__(self):
    return iter(self.subconditions)

  def __len__(self):
    return len(self.subconditions)

  def __getitem__(self, index):
    for i, c in enumerate(self.subconditions):
      if i == index:
        return c
    return None


class IsType(GraphCondition):
  """Accepts iff the target is of the given type.

  This uses the human-readable type aliases, eg 'java_library'. This does not respect inheritance;
  eg, a 'java_library" is not considered to be of type 'target', even though it technically is in
  the internal class model.

  E.g.: {"type": "java_library"}
  """

  def __init__(self, type_):
    self.type_ = type_

  def accept(self, context, target):
    aliases = context.build_file_parser.registered_aliases().target_types_by_alias
    # We want to compare the name directly rather than using isinstance(), because we don't actually
    # want to count subclasses.
    return any(type(target).__name__ == t.__name__ for t in aliases.get(self.type_))


class NameMatches(GraphCondition):
  """Accepts iff the target's name matches the given regex.

  E.g.: {"name": "^(int-)?test$"}
  """

  def __init__(self, pattern):
    self._pattern = re.compile(pattern)

  def accept(self, context, target):
    return self._pattern.match(target.name)


class SpecMatches(GraphCondition):
  """Accepts iff the target's spec matches the given regex.

  E.g.: {"spec": "^service/.*?:lib$"}
  """

  def __init__(self, pattern):
    self._pattern = re.compile(pattern)

  def accept(self, context, target):
    return self._pattern.match(target.address.spec)


class HasSources(GraphCondition):
  """Accepts iff the target has any sources that match the provided extension.

  E.g.: {"sources": "java"}
  """

  def __init__(self, extension=None):
    """
    :param string extension: File extension of source files (or '' to match all sources).
    """
    self.extension = extension or ''

  def accept(self, context, target):
    return target.has_sources(extension=self.extension)


class HasDependency(MetaCondition):
  """Accepts iff the target has a dependency that matches the given conditions.

  E.g.: {"dependency": {"target": {"name": "lib", "type": "java_library"}, "transitive": false}}
  """

  def __init__(self, target, transitive=True):
    """
    :param dict target: A (possibly recursive) conditions map with identical semantics to the outer
      map used to check this target. This conditions map will be checked against every dependency.
    :param transitive: Whether to consider this target's transitive dependencies, or only the direct
      ones. (Defaults to True)
    """
    self.dependency_condition = Conditions(target)
    self.transitive = transitive

  def accept(self, context, target):
    if not self.transitive:
      return any(self.dependency_condition(context, dep) for dep in target.dependencies)
    return any(self.dependency_condition(context, dep) for dep in target.closure() if dep != target)

  @property
  def subconditions(self):
    return [self.dependency_condition]


class HasDependee(MetaCondition):
  """Accepts iff the target has a dependee that matches the given conditions.

  E.g.: {"dependee": {"target": {"name": "test", "type": "java_tests"}, "transitive": false}}
  """

  def __init__(self, target, transitive=True):
    """
    :param dict target: A (possibly recursive) conditions map with identical semantics to the outer
      map used to check this target. This conditions map will be checked against every dependee.
    :param transitive: Whether to consider this target's transitive dependees, or only the direct
      ones. (Defaults to True)
    """
    self.dependee_condition = Conditions(target)
    self.transitive = transitive

  def accept(self, context, target):
    if not self.transitive:
      dependees = (context.build_graph.get_target(addr)
                   for addr in context.build_graph.dependents_of(target.address))
      return any(self.dependee_condition(context, dep) for dep in dependees)
    dependees = set()
    context.build_graph.walk_transitive_dependee_graph([target.address], dependees.add)
    return any(self.dependee_condition(context, dep) for dep in dependees if dep != target)

  @property
  def subconditions(self):
    return [self.dependee_condition]


class All(MetaCondition):
  """Meta-condition that accepts iff all its input conditions accept.

  E.g.: {"all": [{"name": "^test$"}, {"spec": "^service/"}]}
  """

  def __init__(self, *conditions):
    self.conditions = map(Conditions, conditions)

  def accept(self, context, target):
    return all(predicate(context, target) for predicate in self.conditions)

  @property
  def subconditions(self):
    return self.conditions


class Any(MetaCondition):
  """Meta-condition that accepts iff any its input conditions accept.

  E.g.: {"any": [{"name": "test"}, {"name": "int-test"}]}
  """

  def __init__(self, *conditions):
    self.conditions = map(Conditions, conditions)

  def accept(self, context, target):
    return any(predicate(context, target) for predicate in self.conditions)

  @property
  def subconditions(self):
    return self.conditions


class Not(MetaCondition):
  """Meta-condition that accepts iff its input condition does not accept.

  E.g.: {"not": {"name": "test"}}
  """

  def __init__(self, **condition):
    self.condition = Conditions(condition)

  def accept(self, context, target):
    return not(self.condition(context, target))

  @property
  def subconditions(self):
    return [self.condition]


class Conditions(object):
  """Factory for parsing conditions from dicts."""

  conditions_by_alias = {
    'all': All,
    'any': Any,
    'not': Not,
    'type': IsType,
    'name': NameMatches,
    'spec': SpecMatches,
    'dependency': HasDependency,
    'dependee': HasDependee,
    'sources': HasSources,
  }

  @classmethod
  def _create_condition(cls, condition_type, value):
    if isinstance(value, (list, tuple)):
      return condition_type(*value)
    if isinstance(value, dict):
      return condition_type(**value)
    return condition_type(value)

  def __new__(cls, params):
    """
    :param dict params: A dictionary mapping condition names to their parameters.
    """
    if isinstance(params, GraphCondition):
      return params
    conditions = []
    for key, value in params.items():
      if key not in cls.conditions_by_alias:
        raise ValueError('Invalid condition "{}"; must be one of: {}'
                         .format(key, ', '.join(sorted(cls.conditions_by_alias))))
      conditions.append(cls._create_condition(cls.conditions_by_alias[key], value))
    if len(conditions) == 1:
      return conditions[0]
    return All(*conditions)
