# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.optionable import Optionable


class SubsystemError(Exception):
  """An error in a subsystem."""


class Subsystem(Optionable):
  """A separable piece of functionality that may be reused across multiple tasks or other code.

  Subsystems encapsulate the configuration and initialization of things like JVMs,
  Python interpreters, SCMs and so on.

  Subsystem instances can be global or per-optionable. Global instances are useful for representing
  global concepts, such as the SCM used in the workspace. Per-optionable instances allow individual
  Optionable objects (notably, tasks) to have their own configuration for things such as artifact
  caches.

  Each subsystem type has an option scope. The global instance of that subsystem initializes
  itself from options in that scope. An optionable-specific instance initializes itself from options
  in an appropriate subscope, which defaults back to the global scope.

  For example, the global artifact cache options would be in scope `cache`, but the
  compile.java task can override those options in scope `cache.compile.java`.
  """

  @classmethod
  def closure(cls, subsystem_types):
    """Gathers the closure of the `subsystem_types` and their transitive `dependencies`.

    NB: Cycles are tolerated here; however this does not protect any initialization cycles in
    subsystem factory methods.

    :param subsystem_types: An iterable of subsystem types.
    :returns: A set containing the closure of subsystem types reachable from the given
              `subsystem_types` roots.
    """
    # TODO(John Sirois): Consider detecting and failing cycles; there is probably never a legitimate
    # use-case for subsystems with cyclic dependencies.
    known_subsystem_types = set()

    def collect_subsystems(subsystem):
      if subsystem not in known_subsystem_types:
        known_subsystem_types.add(subsystem)
        for dependency in subsystem.dependencies():
          collect_subsystems(dependency)

    for subsystem_type in subsystem_types:
      collect_subsystems(subsystem_type)

    return known_subsystem_types

  @classmethod
  def dependencies(cls):
    """The subsystems this subsystem uses.

    A tuple of subsystem types.
    """
    return tuple()

  @classmethod
  def subscope(cls, scope):
    """Create a subscope under this Subsystem's scope."""
    return '{0}.{1}'.format(cls.options_scope, scope)

  # The full Options object for this pants run.  Will be set after options are parsed.
  # TODO: A less clunky way to make option values available?
  _options = None

  # A cache of (cls, scope) -> the instance of cls tied to that scope.
  _scoped_instances = {}

  @classmethod
  def global_instance(cls):
    """Returns the global instance of this subsystem.

    The global instance is the subsystem singleton instance for the main subsystem `options_scope`.

    :returns: The global subsystem instance.
    :rtype: :class:`pants.subsystem.subsystem.Subsystem`
    """
    return cls._instance_for_scope(cls.options_scope)

  @classmethod
  def scoped_instance(cls, optionable):
    """Returns an instance of this subsystem scoped by the given `optionable`.

    The scoped instance is the subsystem singleton instance for the main subsystem `options_scope`
    qualified by `optionable`'s scope.

    :param optionable: An optionable type or instance to scope this subsystem under.
    :type: :class:`pants.option.optionable.Optionable`
    :returns: The scoped subsystem instance.
    :rtype: :class:`pants.subsystem.subsystem.Subsystem`
    """
    if not isinstance(optionable, Optionable) and not issubclass(optionable, Optionable):
      raise TypeError('Can only scope an instance against an Optionable, given {} of type {}.'
                      .format(optionable, type(optionable)))
    return cls._instance_for_scope(cls.subscope(optionable.options_scope))

  @classmethod
  def _instance_for_scope(cls, scope):
    if cls._options is None:
      raise SubsystemError('Subsystem not initialized yet.')
    key = (cls, scope)
    if key not in cls._scoped_instances:
      cls._scoped_instances[key] = cls(scope, cls._options.for_scope(scope))
    return cls._scoped_instances[key]

  @classmethod
  def reset(cls):
    """Forget all option values and cached subsystem instances.

    Used for test isolation.
    """
    cls._options = None
    cls._scoped_instances = {}

  def __init__(self, scope, scoped_options):
    """Note: A subsystem has no access to options in scopes other than its own.

    TODO: We'd like that to be true of Tasks some day. Subsystems will help with that.

    Task code should call scoped_instance() or global_instance() to get a subsystem instance.
    Tests can call this constructor directly though.
    """
    super(Subsystem, self).__init__()
    self._scope = scope
    self._scoped_options = scoped_options

  @property
  def options_scope(self):
    return self._scope

  def get_options(self):
    """Returns the option values for this subsystem's scope."""
    return self._scoped_options
