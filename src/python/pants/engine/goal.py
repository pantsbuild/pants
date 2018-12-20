# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from contextlib import contextmanager

from pants.cache.cache_setup import CacheSetup
from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin
from pants.util.meta import AbstractClass, classproperty


class Goal(SubsystemClientMixin, Optionable, AbstractClass):
  """A CLI goal whch is implemented by a `@console_rule`.
  
  This abstract class should be subclassed and given a `Goal.name` that it will be referred to by
  when invoked from the command line. The `Goal.name` also acts as the options_scope for the `Goal`.
  """

  # Subclasser-defined. See the class pydoc.
  name = None

  # If this Goal should have an associated deprecated instance of `CacheSetup` (which was implicitly
  # required by all v1 Tasks), subclasses may set this to a valid deprecation version to create
  # that association.
  deprecated_cache_setup_removal_version = None

  @classproperty
  def options_scope(cls):
    if not cls.name:
      # TODO: Would it be unnecessarily magical to have `cls.__name__.lower()` always be the name?
      raise AssertionError('{} must have a `Goal.name` defined.'.format(cls.__name__))
    return cls.name

  @classmethod
  def subsystem_dependencies(cls):
    # NB: `Goal` implements `SubsystemClientMixin` in order to allow v1 `Tasks` to depend on
    # v2 Goals, and for `Goals` to declare a deprecated dependency on a `CacheSetup` instance for
    # backwards compatibility purposes. But v2 Goals should _not_ have subsystem dependencies:
    # instead, the @rules participating (transitively) in a Goal should directly declare
    # Subsystem deps.
    if cls.deprecated_cache_setup_removal_version:
      dep = CacheSetup.scoped(
          cls,
          removal_version=cls.deprecated_cache_setup_removal_version,
          removal_hint='Goal `{}` uses an independent caching implementation, and ignores `{}`.'.format(
            cls.name,
            CacheSetup.subscope(cls.name),
          )
        )
      return (dep,)
    return tuple()

  options_scope_category = ScopeInfo.GOAL

  def __init__(self, scope, scoped_options):
    # NB: This constructor is shaped to meet the contract of `Optionable(Factory).signature`.
    super(Goal, self).__init__()
    self._scope = scope
    self._scoped_options = scoped_options

  @property
  def options(self):
    """Returns the option values for this Goal."""
    return self._scoped_options


class LineOriented(object):
  """A mixin for Goal that adds options and a context manager for line-oriented output."""

  @classmethod
  def register_options(cls, register):
    super(LineOriented, cls).register_options(register)
    register('--sep', default='\\n', metavar='<separator>',
             help='String to use to separate result lines.')
    register('--output-file', metavar='<path>',
             help='Write line-oriented output to this file instead.')

  @contextmanager
  def line_oriented(self, console):
    """Takes a Console and yields functions for writing to stdout and stderr, respectively."""

    output_file = self.options.output_file
    sep = self.options.sep.encode('utf-8').decode('unicode_escape')

    stdout, stderr = console.stdout, console.stderr
    if output_file:
      stdout = open(output_file, 'w')

    try:
      print_stdout = lambda msg: print(msg, file=stdout, end=sep)
      print_stderr = lambda msg: print(msg, file=stderr)
      yield print_stdout, print_stderr
    finally:
      if output_file:
        stdout.close()
      else:
        stdout.flush()
      stderr.flush()
