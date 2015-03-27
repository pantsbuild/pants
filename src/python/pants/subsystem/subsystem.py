# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

from pants.option.options import Options
from pants.util.meta import AbstractClass


class Subsystem(AbstractClass):
  """A separable piece of functionality that may be reused in multiple tasks or other code.

  Subsystems encapsulate the configuration and initialization of things like JVMs,
  Python interpreters, SCMs and so on.

  Currently this is a thin wrapper around reusable config.
  TODO(benjy): Model dependencies between subsystems? Registration of subsystems?
  """
  @abstractproperty
  def scope_qualifier(self):
    """Qualifies the options scope of this Subsystem.

    E.g., the global SubsystemFoo will have scope 'foo', and a SubsystemFoo configured just
    for use in task bar.baz will have scope 'bar.baz.foo'.
    """

  @classmethod
  def register_options_for_global_instance(cls, options):
    """Register options for the global instance of this subsystem.

    Subclasses should not generally need to override this method.
    """
    cls._register_options_on_scope(options, Options.GLOBAL_SCOPE)

  @classmethod
  def register_options_for_per_task_instance(cls, options, task):
    """Register options for a per-task instance of this subsystem.

    Subclasses should not generally need to override this method.
    """
    cls._register_options_on_scope(options, task.options_scope)

  @classmethod
  def _register_options_on_scope(cls, options, scope):
    """Trigger registration of this subsystem's options under a given scope."""
    cls.register_options(options.registration_function_for_scope(cls.qualify_scope(scope)))

  @classmethod
  def register_options(cls, register):
    """Register options for this subsystem.

    Subclasses may override and call register(*args, **kwargs) with argparse arguments.
    """

  @classmethod
  def qualify_scope(cls, scope):
    return '{0}.{1}'.format(scope, cls.scope_qualifier) if scope else cls.scope_qualifier

  # The full Options object for this pants run.  Will be set after options are parsed.
  _options = None
  _scoped_instances = {}

  @classmethod
  def instance_for_scope(cls, scope):
    if scope not in cls._scoped_instances:
      cls._scoped_instances[scope] = cls(cls._options.for_scope(cls.qualify_scope(scope)))
    return cls._scoped_instances[scope]

  @classmethod
  def global_instance(cls):
    return cls.instance_for_scope(Options.GLOBAL_SCOPE)

  def __init__(self, scoped_options):
    """Note: A subsystem has no access to options in global scope or scopes other than its own.

    Task code should prefer to call instance_for_scope() or global_instance() to get a subsystem
    instance.  Tests can call this constructor directly though.

    TODO: We'd like that to be true of Tasks some day. Subsystems will help with that.
    """
    self._scoped_options = scoped_options

  def get_options(self):
    """Returns the option values for this subsystem's scope."""
    return self._scoped_options
