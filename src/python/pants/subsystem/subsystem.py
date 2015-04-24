# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.options import Options


class SubsystemError(Exception):
  """An error in a subsystem."""


class Subsystem(object):
  """A separable piece of functionality that may be reused across multiple tasks or other code.

  Subsystems encapsulate the configuration and initialization of things like JVMs,
  Python interpreters, SCMs and so on.

  Subsystem instances are tied to option scopes. For example, a singleton subsystem that all tasks
  share is tied to the global scope, while a private instance used by just one task is tied to
  that task's scope.

  A Subsystem instance initializes itself from options in a subscope (the 'qualified scope') of
  the scope it's tied to. For example, a global SubsystemFoo instance gets its options from
  scope 'foo', while a SubsystemFoo instance for use just in task bar.baz gets its options from
  scope 'bar.baz.foo'.

  TODO(benjy): Model dependencies between subsystems? Registration of subsystems?
  """
  @classmethod
  def scope_qualifier(cls):
    """Qualifies the options scope of this Subsystem type.

    E.g., for SubsystemFoo this should return 'foo'.
    """
    raise NotImplementedError()

  @classmethod
  def register_options(cls, register):
    """Register options for this subsystem.

    Subclasses may override and call register(*args, **kwargs) with argparse arguments.
    """

  @classmethod
  def register_options_on_scope(cls, options, scope):
    """Trigger registration of this subsystem's options under a given scope."""
    cls.register_options(options.registration_function_for_scope(cls.qualify_scope(scope)))

  @classmethod
  def qualify_scope(cls, scope):
    return '{0}.{1}'.format(scope, cls.scope_qualifier()) if scope else cls.scope_qualifier()

  # The full Options object for this pants run.  Will be set after options are parsed.
  # TODO: A less clunky way to make option values available?
  _options = None

  # A cache of (cls, scope) -> the instance of cls tied to that scope.
  _scoped_instances = {}

  @classmethod
  def global_instance(cls):
    return cls._instance_for_scope(Options.GLOBAL_SCOPE)

  @classmethod
  def reset_instance_for_scope(cls, scope):
    key = (cls, scope)
    cls._scoped_instances.pop(key, None)

  @classmethod
  def reset_global_instance(cls):
    cls.reset_instance_for_scope(Options.GLOBAL_SCOPE)

  @classmethod
  def instance_for_task(cls, task):
    return cls._instance_for_scope(task.options_scope)

  @classmethod
  def _instance_for_scope(cls, scope):
    if cls._options is None:
      raise SubsystemError('Subsystem not initialized yet.')
    key = (cls, scope)
    if key not in cls._scoped_instances:
      qscope = cls.qualify_scope(scope)
      cls._scoped_instances[key] = cls(qscope, cls._options.for_scope(qscope))
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
