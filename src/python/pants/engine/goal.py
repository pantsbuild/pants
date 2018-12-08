# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo
from pants.util.meta import AbstractClass, classproperty


class Goal(Optionable, AbstractClass):
  """A CLI goal whch is implemented by a `@console_rule`.
  
  This abstract class should be subclassed and given a `Goal.name` that it will be referred to by
  when invoked from the command line. The `Goal.name` also acts as the options_scope for the `Goal`.
  """

  # Subclasser-defined. See the class pydoc.
  name = None

  options_scope_category = ScopeInfo.GOAL

  @classproperty
  def options_scope(cls):
    if not cls.name:
      # TODO: Would it be unnecessarily magical to have `cls.__name__.lower()` always be the name?
      raise AssertionError('{} must have a `Goal.name` defined.'.format(cls.__name__))
    return cls.name

  @classmethod
  def subsystem_dependencies_iter(cls):
    # NB: `Goal` quacks like a `SubsystemClientMixin` in order to allow v1 `Tasks` to depend on
    # v2 Goals for backwards compatibility purposes. But v2 Goals should _not_ have subsystem
    # dependencies: instead, the @rules participating (transitively) in a Goal should directly
    # declare Subsystem deps.
    return iter([])

  def __init__(self, scope, scoped_options):
    # NB: This constructor is shaped to meet the contract of `Optionable(Factory).signature`.
    super(Goal, self).__init__()
    self._scope = scope
    self._scoped_options = scoped_options

  @property
  def options(self):
    """Returns the option values for this Goal."""
    return self._scoped_options
