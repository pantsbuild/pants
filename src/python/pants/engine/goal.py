# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, ClassVar, Iterator, Type, cast

from typing_extensions import final

from pants.engine.unions import UnionMembership
from pants.option.option_types import StrOption
from pants.option.scope import ScopeInfo
from pants.option.subsystem import Subsystem
from pants.util.meta import classproperty

if TYPE_CHECKING:
    from pants.engine.console import Console


class GoalSubsystem(Subsystem):
    """The Subsystem used by `Goal`s to register the external API, meaning the goal name, the help
    message, and any options.

    This class should be subclassed and given a `GoalSubsystem.name` that it will be referred to by
    when invoked from the command line. The `Goal.name` also acts as the options_scope for the Goal.

    Rules that need to consume the GoalSubsystem's options may directly request the type:

    ```
    @rule
    def list(console: Console, list_subsystem: ListSubsystem) -> List:
      transitive = list_subsystem.transitive
      documented = list_subsystem.documented
      ...
    ```
    """

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        """Return `False` if this goal should not show up in `./pants help`.

        Usually this is determined by checking `MyType in union_membership`.
        """
        return True

    @classmethod
    def create_scope_info(cls, **scope_info_kwargs) -> ScopeInfo:
        return super().create_scope_info(is_goal=True, **scope_info_kwargs)

    @classproperty
    @abstractmethod
    def name(cls):
        """The name used to select the corresponding Goal on the commandline and the options_scope
        for its options."""

    @classproperty
    def options_scope(cls) -> str:
        return cast(str, cls.name)


@dataclass(frozen=True)
class Goal:
    """The named product of a `@goal_rule`.

    This class should be subclassed and linked to a corresponding `GoalSubsystem`:

    ```
    class ListSubsystem(GoalSubsystem):
      '''List targets.'''
      name = "list"

    class List(Goal):
      subsystem_cls = ListSubsystem
    ```

    Since `@goal_rules` always run in order to produce side effects (generally: console output),
    they are not cacheable, and the `Goal` product of a `@goal_rule` contains only a exit_code
    value to indicate whether the rule exited cleanly.
    """

    exit_code: int
    subsystem_cls: ClassVar[Type[GoalSubsystem]]

    @final
    @classproperty
    def name(cls) -> str:
        return cast(str, cls.subsystem_cls.name)


class Outputting:
    """A mixin for Goal that adds options to support output-related context managers.

    Allows output to go to a file or to stdout.

    Useful for goals whose purpose is to emit output to the end user (as distinct from incidental logging to stderr).
    """

    output_file = StrOption(
        default=None,
        metavar="<path>",
        help="Output the goal's stdout to this file. If unspecified, outputs to stdout.",
    )

    @final
    @contextmanager
    def output(self, console: "Console") -> Iterator[Callable[[str], None]]:
        """Given a Console, yields a function for writing data to stdout, or a file.

        The passed options instance will generally be the `Goal.Options` of an `Outputting` `Goal`.
        """
        with self.output_sink(console) as output_sink:
            yield lambda msg: output_sink.write(msg)  # type: ignore[no-any-return]

    @final
    @contextmanager
    def output_sink(self, console: "Console") -> Iterator:
        stdout_file = None
        if self.output_file:
            stdout_file = open(self.output_file, "w")
            output_sink = stdout_file
        else:
            output_sink = console.stdout  # type: ignore[assignment]
        try:
            yield output_sink
        finally:
            output_sink.flush()
            if stdout_file:
                stdout_file.close()


class LineOriented(Outputting):
    sep = StrOption(
        default="\\n",
        metavar="<separator>",
        help="String to use to separate lines in line-oriented output.",
    )

    @final
    @contextmanager
    def line_oriented(self, console: "Console") -> Iterator[Callable[[str], None]]:
        """Given a Console, yields a function for printing lines to stdout or a file.

        The passed options instance will generally be the `Goal.Options` of an `Outputting` `Goal`.
        """
        sep = self.sep.encode().decode("unicode_escape")
        with self.output_sink(console) as output_sink:
            yield lambda msg: print(msg, file=output_sink, end=sep)
