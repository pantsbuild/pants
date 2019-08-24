# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from contextlib import contextmanager

from pants.cache.cache_setup import CacheSetup
from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin
from pants.util.memo import memoized_classproperty
from pants.util.meta import classproperty
from pants.util.objects import datatype


class Goal(datatype([('exit_code', int)]), metaclass=ABCMeta):
  """The named product of a `@console_rule`.

  This abstract class should be subclassed and given a `Goal.name` that it will be referred to by
  when invoked from the command line. The `Goal.name` also acts as the options_scope for the `Goal`.

  Since `@console_rules` always run in order to produce side effects (generally: console output), they
  are not cacheable, and the `Goal` product of a `@console_rule` contains only a exit_code value to
  indicate whether the rule exited cleanly.

  Options values for a Goal can be retrived by declaring a dependency on the relevant `Goal.Options`
  class.
  """

  @classproperty
  @abstractmethod
  def name(cls):
    """The name used to select this Goal on the commandline, and for its options."""

  @classproperty
  def deprecated_cache_setup_removal_version(cls):
    """Optionally defines a deprecation version for a CacheSetup dependency.

    If this Goal should have an associated deprecated instance of `CacheSetup` (which was implicitly
    required by all v1 Tasks), subclasses may set this to a valid deprecation version to create
    that association.
    """
    return None

  @classmethod
  def register_options(cls, register):
    """Register options for the `Goal.Options` of this `Goal`.

    Subclasses may override and call register(*args, **kwargs). Callers can retrieve the resulting
    options values by declaring a dependency on the `Goal.Options` class.
    """

  @memoized_classproperty
  def Options(cls):
    # NB: The naming of this property is terribly evil. But this construction allows the inner class
    # to get a reference to the outer class, which avoids implementers needing to subclass the inner
    # class in order to define their options values, while still allowing for the useful namespacing
    # of `Goal.Options`.
    outer_cls = cls
    class _Options(SubsystemClientMixin, Optionable, _GoalOptions):
      @classproperty
      def options_scope(cls):
        return outer_cls.name

      @classmethod
      def register_options(cls, register):
        super(_Options, cls).register_options(register)
        # Delegate to the outer class.
        outer_cls.register_options(register)

      @classmethod
      def subsystem_dependencies(cls):
        # NB: `Goal.Options` implements `SubsystemClientMixin` in order to allow v1 `Tasks` to
        # depend on v2 Goals, and for `Goals` to declare a deprecated dependency on a `CacheSetup`
        # instance for backwards compatibility purposes. But v2 Goals should _not_ have subsystem
        # dependencies: instead, the @rules participating (transitively) in a Goal should directly
        # declare their Subsystem deps.
        if outer_cls.deprecated_cache_setup_removal_version:
          dep = CacheSetup.scoped(
              cls,
              removal_version=outer_cls.deprecated_cache_setup_removal_version,
              removal_hint='Goal `{}` uses an independent caching implementation, and ignores `{}`.'.format(
                cls.options_scope,
                CacheSetup.subscope(cls.options_scope),
              )
            )
          return (dep,)
        return tuple()

      options_scope_category = ScopeInfo.GOAL

      def __init__(self, scope, scoped_options):
        # NB: This constructor is shaped to meet the contract of `Optionable(Factory).signature`.
        super(_Options, self).__init__()
        self._scope = scope
        self._scoped_options = scoped_options

      @property
      def values(self):
        """Returns the option values for these Goal.Options."""
        return self._scoped_options
    _Options.__doc__ = outer_cls.__doc__
    return _Options


class _GoalOptions(object):
  """A marker trait for the anonymous inner `Goal.Options` classes for `Goal`s."""


class LineOriented:
  """A mixin for Goal that adds Options to support the `line_oriented` context manager."""

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--sep', default='\\n', metavar='<separator>',
             help='String to use to separate result lines.')
    register('--output-file', metavar='<path>',
             help='Write line-oriented output to this file instead.')

  @classmethod
  @contextmanager
  def line_oriented(cls, line_oriented_options, console):
    """Given Goal.Options and a Console, yields functions for writing to stdout and stderr, respectively.

    The passed options instance will generally be the `Goal.Options` of a `LineOriented` `Goal`.
    """
    if type(line_oriented_options) != cls.Options:
      raise AssertionError(
          'Expected Options for `{}`, got: {}'.format(cls.__name__, line_oriented_options))

    output_file = line_oriented_options.values.output_file
    sep = line_oriented_options.values.sep.encode().decode('unicode_escape')

    if output_file:
      stdout_file = open(output_file, 'w')
      print_stdout = lambda msg: print(msg, file=stdout_file, end=sep)
    else:
      print_stdout = lambda msg: console.print_stdout(msg, end=sep)

    print_stderr = lambda msg: console.print_stderr(msg)

    try:
      yield print_stdout, print_stderr
    finally:
      if output_file:
        stdout_file.close()
      console.flush()
