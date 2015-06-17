# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class SubsystemError(Exception):
  """An error in a subsystem."""


class Subsystem(object):
  """A separable piece of functionality that may be reused across multiple tasks or other code.

  Subsystems encapsulate the configuration and initialization of things like JVMs,
  Python interpreters, SCMs and so on.

  Subsystem instances can be global or per-task. Global instances are useful for representing
  global concepts, such as the SCM used in the workspace. Per-task instances allow individual
  tasks to have their own configuration for things such as artifact caches.

  Each subsystem type has an option scope. The global instance of that subsystem initializes
  itself from options in that scope. A task-specific instance initializes itself from options in
  an appropriate subscope, which defaults back to the global scope.

  For example, the global artifact cache setup would be in scope `cache`, but the
  compile.java task can override that setup in scope `cache.compile.java`.

  TODO(benjy): Model dependencies between subsystems? Registration of subsystems?
  """
  # Subclasses should override.
  options_scope = None

  @classmethod
  def subscope(cls, scope):
    """Create a subscope under this Subsystem's main scope."""
    return '{0}.{1}'.format(cls.options_scope, scope)

  @classmethod
  def register_options(cls, register):
    """Register options for this subsystem.

    Subclasses may override and call register(*args, **kwargs) with argparse arguments.
    """

  @classmethod
  def register_options_on_scope(cls, options, scope):
    """Trigger registration of this subsystem's options under a given scope."""
    cls.register_options(options.registration_function_for_scope(scope))

  # The full Options object for this pants run.  Will be set after options are parsed.
  # TODO: A less clunky way to make option values available?
  _options = None

  # A cache of (cls, scope) -> the instance of cls tied to that scope.
  _scoped_instances = {}

  @classmethod
  def global_instance(cls):
    return cls._instance_for_scope(cls.options_scope)

  @classmethod
  def reset(cls):
    """Forget all option values and cached subsystem instances.

    Used for test isolation.
    """
    cls._options = None
    cls._scoped_instances = {}

  @classmethod
  def instance_for_task(cls, task):
    return cls._instance_for_scope(cls.subscope(task.options_scope))

  @classmethod
  def _instance_for_scope(cls, scope):
    if cls._options is None:
      raise SubsystemError('Subsystem not initialized yet.')
    key = (cls, scope)
    if key not in cls._scoped_instances:
      cls._scoped_instances[key] = cls(scope, cls._options.for_scope(scope))
    return cls._scoped_instances[key]

  def __init__(self, scope, scoped_options):
    """Note: A subsystem has no access to options in scopes other than its own.

    TODO: We'd like that to be true of Tasks some day. Subsystems will help with that.

    Task code should call instance_for_scope() or global_instance() to get a subsystem instance.
    Tests can call this constructor directly though.
    """
    self._scope = scope
    self._scoped_options = scoped_options

  @property
  def options_scope(self):
    return self._scope

  def get_options(self):
    """Returns the option values for this subsystem's scope."""
    return self._scoped_options
