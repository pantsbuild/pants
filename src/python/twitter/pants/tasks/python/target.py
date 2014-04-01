# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet

from pants.base.parse_context import ParseContext
from pants.base.target import Target, TargetDefinitionException
from pants.targets.python_requirement import PythonRequirement


def is_python_root(target):
  return isinstance(target, PythonRoot)


class PythonRoot(Target):
  """
    Internal target for managing python chroot state.
  """
  @classmethod
  def synthetic_name(cls, targets):
    return list(targets)[0].name if len(targets) > 0 else 'empty'

  @classmethod
  def union(cls, targets, name=None):
    name = name or (cls.synthetic_name(targets) + '-union')
    with ParseContext.temp():
      return cls(name, dependencies=targets)

  @classmethod
  def of(cls, target):
    with ParseContext.temp():
      return cls(target.name, dependencies=[target])

  def __init__(self, name, dependencies=None):
    self.dependencies = OrderedSet(dependencies) if dependencies else OrderedSet()
    self.internal_dependencies = OrderedSet()
    self.interpreters = []
    self.distributions = {} # interpreter => distributions
    self.chroots = {}       # interpreter => chroots
    super(PythonRoot, self).__init__(name)

  def closure(self):
    os = OrderedSet()
    for target in self.dependencies | self.internal_dependencies:
      os.update(target.closure())
    return os

  def select(self, target_class):
    return OrderedSet(target for target in self.closure() if isinstance(target, target_class))

  @property
  def requirements(self):
    return self.select(PythonRequirement)
