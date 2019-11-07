# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass

from pants.cache.cache_setup import CacheSetup
from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin
from pants.util.memo import memoized_classproperty
from pants.util.meta import classproperty


@dataclass(frozen=True)
# type: ignore # tracked by https://github.com/python/mypy/issues/5374, which they put as high priority.
class Goal(metaclass=ABCMeta):
  """The named product of a `@console_rule`.

  This abstract class should be subclassed and given a `Goal.name` that it will be referred to by
  when invoked from the command line. The `Goal.name` also acts as the options_scope for the `Goal`.

  Since `@console_rules` always run in order to produce side effects (generally: console output), they
  are not cacheable, and the `Goal` product of a `@console_rule` contains only a exit_code value to
  indicate whether the rule exited cleanly.

  Options values for a Goal can be retrived by declaring a dependency on the relevant `Goal.Options`
  class.
  """
  exit_code: int

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


class Outputting:
  """A mixin for Goal that adds options to support output-related context managers.

  Allows output to go to a file or to stdout.

  Useful for goals whose purpose is to emit output to the end user (as distinct from incidental logging to stderr).
  """

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--output-file', metavar='<path>',
             help='Output to this file.  If unspecified, outputs to stdout.')

  @classmethod
  @contextmanager
  def output(cls, options, console):
    """Given Goal.Options and a Console, yields a function for writing data to stdout, or a file.

    The passed options instance will generally be the `Goal.Options` of an `Outputting` `Goal`.
    """
    with cls.output_sink(options, console) as output_sink:
      yield lambda msg: output_sink.write(msg)

  @classmethod
  @contextmanager
  def output_sink(cls, options, console):
    if type(options) != cls.Options:
      raise AssertionError('Expected Options for `{}`, got: {}'.format(cls.__name__, options))
    stdout_file = None
    if options.values.output_file:
      stdout_file = open(options.values.output_file, 'w')
      output_sink = stdout_file
    else:
      output_sink = console.stdout
    try:
      yield output_sink
    finally:
      output_sink.flush()
      if stdout_file:
        stdout_file.close()


class LineOriented(Outputting):
  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--sep', default='\\n', metavar='<separator>',
             help='String to use to separate lines in line-oriented output.')

  @classmethod
  @contextmanager
  def line_oriented(cls, options, console):
    """Given Goal.Options and a Console, yields a function for printing lines to stdout or a file.

    The passed options instance will generally be the `Goal.Options` of an `Outputting` `Goal`.
    """
    sep = options.values.sep.encode().decode('unicode_escape')
    with cls.output_sink(options, console) as output_sink:
      yield lambda msg: print(msg, file=output_sink, end=sep)
