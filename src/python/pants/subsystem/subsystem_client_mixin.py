# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple

from pants.option.arg_splitter import GLOBAL_SCOPE


class SubsystemClientError(Exception): pass


class SubsystemDependency(namedtuple('_SubsystemDependency', ('subsystem_cls', 'scope'))):
  """Indicates intent to use an instance of `subsystem_cls` scoped to `scope`."""

  def is_global(self):
    return self.scope == GLOBAL_SCOPE

  def options_scope(self):
    """The subscope for options of `subsystem_cls` scoped to `scope`.

    This is the scope that option values are read from when initializing the instance
    indicated by this dependency.
    """
    if self.is_global():
      return self.subsystem_cls.options_scope
    else:
      return self.subsystem_cls.subscope(self.scope)


class SubsystemClientMixin(object):
  """A mixin for declaring dependencies on subsystems."""

  @classmethod
  def subsystem_dependencies(cls):
    """The subsystems this object uses.

    Override to specify your subsystem dependencies. Always add them to your superclass's value.

    Note: Do not call this directly to retrieve dependencies. See subsystem_dependencies_iter().

    :return: A tuple of SubsystemDependency instances.
             In the common case where you're an optionable and you want to get an instance scoped
             to you, call subsystem_cls.scoped(cls) to get an appropriate SubsystemDependency.
             As a convenience, you may also provide just a subsystem_cls, which is shorthand for
             SubsystemDependency(subsystem_cls, GLOBAL SCOPE) and indicates that we want to use
             the global instance of that subsystem.
    """
    return tuple()

  @classmethod
  def subsystem_dependencies_iter(cls):
    for dep in cls.subsystem_dependencies():
      if isinstance(dep, SubsystemDependency):
        yield dep
      else:
        yield SubsystemDependency(dep, GLOBAL_SCOPE)
