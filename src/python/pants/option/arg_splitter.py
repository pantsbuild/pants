# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

from pants.base.deprecated import warn_or_error
from pants.engine.internals.native_engine import PyArgSplitter
from pants.option.scope import ScopeInfo


class ArgSplitterError(Exception):
    pass


@dataclass(frozen=True)
class SplitArgs:
    """The result of splitting args."""

    builtin_or_auxiliary_goal: str | None  # Requested builtin goal (explicitly or implicitly).
    goals: list[str]  # Explicitly requested goals.
    unknown_goals: list[str]  # Any unknown goals.
    specs: list[str]  # The specifications for what to run against, e.g. the targets or files/dirs.
    passthru: list[str]  # Any remaining args specified after a -- separator.


class HelpRequest(ABC):
    """Represents an implicit or explicit request for help by the user."""


@dataclass(frozen=True)
class ThingHelp(HelpRequest):
    """The user requested help on one or more things: e.g., an options scope or a target type."""

    advanced: bool = False
    things: tuple[str, ...] = ()
    likely_specs: tuple[str, ...] = ()


class VersionHelp(HelpRequest):
    """The user asked for the version of this instance of pants."""


class AllHelp(HelpRequest):
    """The user requested a dump of all help info."""


@dataclass(frozen=True)
class UnknownGoalHelp(HelpRequest):
    """The user specified an unknown goal (or task)."""

    unknown_goals: tuple[str, ...]


class NoGoalHelp(HelpRequest):
    """The user specified no goals."""


# These are the names for the built in goals to print help message when there is no goal, or any
# unknown goals respectively. They begin with underlines to exclude them from the list of goals in
# the goal help output.
NO_GOAL_NAME = "__no_goal"
UNKNOWN_GOAL_NAME = "__unknown_goal"


class ArgSplitter:
    """Splits a command-line into scoped sets of flags and a set of specs.

    Recognizes, e.g.:

    pants check --foo lint target1: dir f.ext
    pants --global-opt check target1: dir f.ext --check-flag
    pants --check-flag check target1: dir f.ext
    pants goal -- passthru foo
    """

    def __init__(self, known_scope_infos: Iterable[ScopeInfo], buildroot: str) -> None:
        self._known_goal_scopes = dict(self._get_known_goal_scopes(known_scope_infos))
        self._native_arg_splitter = PyArgSplitter(buildroot, list(self._known_goal_scopes.keys()))

    @staticmethod
    def _get_known_goal_scopes(
        known_scope_infos: Iterable[ScopeInfo],
    ) -> Iterator[tuple[str, ScopeInfo]]:
        for si in known_scope_infos:
            if not si.is_goal:
                continue
            yield si.scope, si
            for alias in si.scope_aliases:
                yield alias, si

    def split_args(self, args: Sequence[str]) -> SplitArgs:
        native_split_args = self._native_arg_splitter.split_args(list(args))

        builtin_or_auxiliary_goal: str | None = None
        canonical_goals = []
        for goal in native_split_args.goals():
            si = self._known_goal_scopes.get(goal)
            if not si or not si.scope:
                continue  # Should never happen.

            if (
                si.deprecated_scope
                and goal == si.deprecated_scope
                and si.subsystem_cls
                and si.deprecated_scope_removal_version
            ):
                warn_or_error(
                    si.deprecated_scope_removal_version,
                    f"the {si.deprecated_scope} goal",
                    f"The {si.deprecated_scope} goal was renamed to {si.subsystem_cls.options_scope}",
                )

            if (si.is_builtin or si.is_auxiliary) and (
                builtin_or_auxiliary_goal is None or goal.startswith("-")
            ):
                if builtin_or_auxiliary_goal:
                    canonical_goals.append(builtin_or_auxiliary_goal)
                builtin_or_auxiliary_goal = si.scope
            else:
                canonical_goals.append(si.scope)

        if not builtin_or_auxiliary_goal:
            if native_split_args.unknown_goals() and UNKNOWN_GOAL_NAME in self._known_goal_scopes:
                builtin_or_auxiliary_goal = UNKNOWN_GOAL_NAME
            elif not canonical_goals and NO_GOAL_NAME in self._known_goal_scopes:
                builtin_or_auxiliary_goal = NO_GOAL_NAME

        return SplitArgs(
            builtin_or_auxiliary_goal=builtin_or_auxiliary_goal,
            goals=canonical_goals,
            unknown_goals=native_split_args.unknown_goals(),
            specs=native_split_args.specs(),
            passthru=native_split_args.passthru(),
        )
