# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from abc import ABC
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Iterable, Iterator, Sequence

from pants.base.deprecated import warn_or_error
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.util.ordered_set import OrderedSet


class ArgSplitterError(Exception):
    pass


@dataclass(frozen=True)
class SplitArgs:
    """The result of splitting args."""

    builtin_or_auxiliary_goal: str | None  # Requested builtin goal (explicitly or implicitly).
    goals: list[str]  # Explicitly requested goals.
    unknown_goals: list[str]  # Any unknown goals.
    scope_to_flags: dict[str, list[str]]  # Scope name -> list of flags in that scope.
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
        self._buildroot = buildroot
        self._known_scope_infos = known_scope_infos
        self._known_goal_scopes = dict(self._get_known_goal_scopes(known_scope_infos))
        self._known_scopes = {si.scope for si in known_scope_infos} | set(
            self._known_goal_scopes.keys()
        )

        # Holds aliases like `-h` for `--help`. Used for disambiguation with ignore specs like
        # `-dir::`.
        self._single_dash_goal_aliases = {
            scope
            for scope in self._known_goal_scopes.keys()
            if scope.startswith("-") and not scope.startswith("--")
        }

        # We store in reverse order, for efficient popping off the end.
        self._unconsumed_args: list[str] = []

        # We allow --scope-flag-name anywhere on the cmd line, as an alternative to ...
        # scope --flag-name.

        # We check for prefixes in reverse order, so we match the longest prefix first.
        sorted_scope_infos = sorted(
            (si for si in self._known_scope_infos if si.scope),
            key=lambda si: si.scope,
            reverse=True,
        )

        # List of pairs (prefix, ScopeInfo).
        self._known_scoping_prefixes = [(f"{si.scope}-", si) for si in sorted_scope_infos]

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
        """Split the specified arg list (or sys.argv if unspecified).

        args[0] is ignored.

        Returns a SplitArgs tuple.
        """
        goals: OrderedSet[str] = OrderedSet()
        scope_to_flags: DefaultDict[str, list[str]] = defaultdict(list)
        specs: list[str] = []
        passthru: list[str] = []
        unknown_scopes: list[str] = []
        builtin_or_auxiliary_goal: str | None = None

        def add_scope(s: str) -> None:
            # Force the scope to appear, even if empty.
            if s not in scope_to_flags:
                scope_to_flags[s] = []

        def add_goal(scope: str) -> str:
            """Returns the scope name to assign flags to."""
            scope_info = self._known_goal_scopes.get(scope)
            if not scope_info:
                unknown_scopes.append(scope)
                add_scope(scope)
                return scope

            nonlocal builtin_or_auxiliary_goal
            if (scope_info.is_builtin or scope_info.is_auxiliary) and (
                not builtin_or_auxiliary_goal or scope.startswith("-")
            ):
                if builtin_or_auxiliary_goal:
                    goals.add(builtin_or_auxiliary_goal)

                # Get scope from info in case we hit an aliased builtin/daemon goal.
                builtin_or_auxiliary_goal = scope_info.scope
            else:
                goals.add(scope_info.scope)
            add_scope(scope_info.scope)

            # Use builtin/daemon goal as default scope for args.
            return builtin_or_auxiliary_goal or scope_info.scope

        self._unconsumed_args = list(reversed(args))
        # The first token is the binary name, so skip it.
        self._unconsumed_args.pop()

        def assign_flag_to_scope(flg: str, default_scope: str) -> None:
            flag_scope, descoped_flag = self._descope_flag(flg, default_scope=default_scope)
            scope_to_flags[flag_scope].append(descoped_flag)

        global_flags = self._consume_flags()
        add_scope(GLOBAL_SCOPE)
        for flag in global_flags:
            assign_flag_to_scope(flag, GLOBAL_SCOPE)

        scope, flags = self._consume_scope()
        while scope:
            # `add_goal` returns the currently active scope to assign flags to.
            scope = add_goal(scope)
            for flag in flags:
                assign_flag_to_scope(flag, GLOBAL_SCOPE if self.is_level_short_arg(flag) else scope)
            scope, flags = self._consume_scope()

        while self._unconsumed_args and not self._at_standalone_double_dash():
            if self._at_flag():
                arg = self._unconsumed_args.pop()
                # We assume any args here are in global scope.
                assign_flag_to_scope(arg, GLOBAL_SCOPE)
                continue

            arg = self._unconsumed_args.pop()
            if self.likely_a_spec(arg):
                specs.append(arg)
            else:
                add_goal(arg)

        if not builtin_or_auxiliary_goal:
            if unknown_scopes and UNKNOWN_GOAL_NAME in self._known_goal_scopes:
                builtin_or_auxiliary_goal = UNKNOWN_GOAL_NAME
            elif not goals and NO_GOAL_NAME in self._known_goal_scopes:
                builtin_or_auxiliary_goal = NO_GOAL_NAME

        if self._at_standalone_double_dash():
            self._unconsumed_args.pop()
            passthru = list(reversed(self._unconsumed_args))

        for goal in goals:
            si = self._known_goal_scopes[goal]
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

        return SplitArgs(
            builtin_or_auxiliary_goal=builtin_or_auxiliary_goal,
            goals=list(goals),
            unknown_goals=unknown_scopes,
            scope_to_flags=dict(scope_to_flags),
            specs=specs,
            passthru=passthru,
        )

    def likely_a_spec(self, arg: str) -> bool:
        """Return whether `arg` looks like a spec, rather than a goal name."""
        # Check if it's an ignore spec.
        if (
            arg.startswith("-")
            and arg not in self._single_dash_goal_aliases
            and not arg.startswith("--")
        ):
            return True
        return any(c in arg for c in (os.path.sep, ".", ":", "*", "#")) or os.path.exists(
            os.path.join(self._buildroot, arg)
        )

    def _consume_scope(self) -> tuple[str | None, list[str]]:
        """Returns a pair (scope, list of flags encountered in that scope).

        Note that the flag may be explicitly scoped, and therefore not actually belong to this scope.

        For example, in:

            pants --check-some-opt=100 check <target>

        --check-some-opt should be treated as if it were --check-some-opt=100 in the check scope.
        """
        if not self._at_scope():
            return None, []
        scope = self._unconsumed_args.pop()
        flags = self._consume_flags()
        return scope, flags

    def _consume_flags(self) -> list[str]:
        """Read flags until we encounter the first token that isn't a flag."""
        flags = []
        while self._at_flag():
            flag = self._unconsumed_args.pop()
            flags.append(flag)
        return flags

    def _descope_flag(self, flag: str, default_scope: str) -> tuple[str, str]:
        """If the flag is prefixed by its scope, extract the scope.

        Otherwise assume it belongs to default_scope.

        Returns a pair (scope, flag).
        """
        for scope_prefix, scope_info in self._known_scoping_prefixes:
            for flag_prefix in ["--", "--no-"]:
                prefix = flag_prefix + scope_prefix
                if not flag.startswith(prefix):
                    continue
                return scope_info.scope, flag_prefix + flag[len(prefix) :]

        return default_scope, flag

    def _at_flag(self) -> bool:
        if not self._unconsumed_args:
            return False
        arg = self._unconsumed_args[-1]
        if not arg.startswith("--") and not self.is_level_short_arg(arg):
            return False
        return not self._at_standalone_double_dash() and not self._at_scope()

    def _at_scope(self) -> bool:
        return bool(self._unconsumed_args) and self._unconsumed_args[-1] in self._known_scopes

    def _at_standalone_double_dash(self) -> bool:
        """At the value `--`, used to start passthrough args."""
        return bool(self._unconsumed_args) and self._unconsumed_args[-1] == "--"

    def is_level_short_arg(self, arg: str) -> bool:
        """We special case the `--level` global option to also be recognized with `-l`.

        It's important that this be classified as a global option.

        Note that we also need to recognize `-h` and `-v` as builtin goals. That is handled already
        via `likely_a_spec()`.
        """
        return arg in {"-ltrace", "-ldebug", "-linfo", "-lwarn", "-lerror"}
