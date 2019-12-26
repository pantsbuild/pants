# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import ClassVar, Type

from pants.cache.cache_setup import CacheSetup
from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin
from pants.util.meta import classproperty


class GoalSubsystem(SubsystemClientMixin, Optionable):
  """The Subsystem used by `Goal`s to register the external API, meaning the goal name, the help
  message, and any options.

  This class should be subclassed and given a `GoalSubsystem.name` that it will be referred to by
  when invoked from the command line. The `Goal.name` also acts as the options_scope for the Goal.

  Rules that need to consume the GoalSubsystem's options may directly request the type:

  ```
  @rule
  def list(console: Console, options: ListOptions) -> List:
    transitive = options.values.transitive
    documented = options.values.documented
    ...
  ```
  """

  @classproperty
  @abstractmethod
  def name(cls):
    """The name used to select the corresponding Goal on the commandline and the options_scope for
    its options."""

  @classproperty
  def deprecated_cache_setup_removal_version(cls):
    """Optionally defines a deprecation version for a CacheSetup dependency.

    If this GoalSubsystem should have an associated deprecated instance of `CacheSetup` (which was
    implicitly required by all v1 Tasks), subclasses may set this to a valid deprecation version to
    create that association.
    """
    return None

  @classproperty
  def options_scope(cls):
    return cls.name

  @classmethod
  def subsystem_dependencies(cls):
    # NB: `GoalSubsystem` implements `SubsystemClientMixin` in order to allow v1 `Tasks` to
    # depend on v2 Goals, and for `Goals` to declare a deprecated dependency on a `CacheSetup`
    # instance for backwards compatibility purposes. But v2 Goals should _not_ have subsystem
    # dependencies: instead, the @rules participating (transitively) in a Goal should directly
    # declare their Subsystem deps.
    if cls.deprecated_cache_setup_removal_version:
      dep = CacheSetup.scoped(
        cls,
        removal_version=cls.deprecated_cache_setup_removal_version,
        removal_hint='Goal `{}` uses an independent caching implementation, and ignores `{}`.'.format(
          cls.options_scope,
          CacheSetup.subscope(cls.options_scope),
        )
      )
      return dep,
    return tuple()

  options_scope_category = ScopeInfo.GOAL

  def __init__(self, scope, scoped_options):
    # NB: This constructor is shaped to meet the contract of `Optionable(Factory).signature`.
    super().__init__()
    self._scope = scope
    self._scoped_options = scoped_options

  @property
  def values(self):
    """Returns the option values."""
    return self._scoped_options


@dataclass(frozen=True)
class Goal:
  """The named product of a `@console_rule`.

  This class should be subclassed and linked to a corresponding `GoalSubsystem`:

  ```
  class ListOptions(GoalSubsystem):
    '''List targets.'''
    name = "list"

  class List(Goal):
    subsystem_cls = ListOptions
  ```

  Since `@console_rules` always run in order to produce side effects (generally: console output),
  they are not cacheable, and the `Goal` product of a `@console_rule` contains only a exit_code
  value to indicate whether the rule exited cleanly.
  """
  exit_code: int
  subsystem_cls: ClassVar[Type[GoalSubsystem]]

  @classproperty
  def name(cls):
    return cls.subsystem_cls.name


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

  @contextmanager
  def output(self, console):
    """Given a Console, yields a function for writing data to stdout, or a file.

    The passed options instance will generally be the `Goal.Options` of an `Outputting` `Goal`.
    """
    with self.output_sink(self, console) as output_sink:
      yield lambda msg: output_sink.write(msg)

  @contextmanager
  def output_sink(self, console):
    stdout_file = None
    if self.values.output_file:
      stdout_file = open(self.values.output_file, 'w')
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

  @contextmanager
  def line_oriented(self, console):
    """Given a Console, yields a function for printing lines to stdout or a file.

    The passed options instance will generally be the `Goal.Options` of an `Outputting` `Goal`.
    """
    sep = self.values.sep.encode().decode('unicode_escape')
    with self.output_sink(console) as output_sink:
      yield lambda msg: print(msg, file=output_sink, end=sep)
