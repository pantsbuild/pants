# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os.path
from abc import ABC
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Iterable, Sequence

from pants.base.deprecated import warn_or_error
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.util.ordered_set import OrderedSet


class ArgSplitterError(Exception):
    pass


@dataclass(frozen=True)
class SplitArgs:
    """The result of splitting args."""

    goals: list[str]  # Explicitly requested goals.
    scope_to_flags: dict[str, list[str]]  # Scope name -> list of flags in that scope.
    specs: list[str]  # The specifications for what to run against, e.g. the targets or files/dirs
    passthru: list[str]  # Any remaining args specified after a -- separator.


class HelpRequest(ABC):
    """Represents an implicit or explicit request for help by the user."""


@dataclass(frozen=True)
class ThingHelp(HelpRequest):
    """The user requested help on one or more things: e.g., an options scope or a target type."""

    advanced: bool = False
    things: tuple[str, ...] = ()


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


class ArgSplitter:
    """Splits a command-line into scoped sets of flags and a set of specs.

    Recognizes, e.g.:

    ./pants check --foo lint -y target1: dir f.ext
    ./pants check --foo lint -y target1: dir f.ext
    ./pants --global-opt check target1: dir f.ext --check-flag
    ./pants --check-flag check target1: dir f.ext
    ./pants goal -- passthru foo

    Handles help and version args specially.
    """

    _HELP_BASIC_ARGS = ("-h", "--help", "help")
    _HELP_ADVANCED_ARGS = ("--help-advanced", "help-advanced")
    _HELP_VERSION_ARGS = ("-v", "-V", "--version", "version")
    _HELP_ALL_SCOPES_ARGS = ("help-all",)
    _HELP_ARGS = (
        *_HELP_BASIC_ARGS,
        *_HELP_ADVANCED_ARGS,
        *_HELP_VERSION_ARGS,
        *_HELP_ALL_SCOPES_ARGS,
    )

    def __init__(self, known_scope_infos: Iterable[ScopeInfo], buildroot: str) -> None:
        self._buildroot = buildroot
        self._known_scope_infos = known_scope_infos
        self._known_scopes = {si.scope for si in known_scope_infos} | {
            "version",
            "help",
            "help-advanced",
            "help-all",
        }
        self._known_goal_scopes = {si.scope: si for si in known_scope_infos if si.is_goal}
        self._unconsumed_args: list[
            str
        ] = []  # In reverse order, for efficient popping off the end.
        self._help_request: HelpRequest | None = None  # Will be set if we encounter any help flags.

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

    @property
    def help_request(self) -> HelpRequest | None:
        return self._help_request

    def _check_for_help_request(self, arg: str) -> bool:
        if arg not in self._HELP_ARGS:
            return False
        if arg in self._HELP_VERSION_ARGS:
            self._help_request = VersionHelp()
        elif arg in self._HELP_ALL_SCOPES_ARGS:
            self._help_request = AllHelp()
        else:
            # First ensure that we have a basic OptionsHelp.
            if not self._help_request:
                self._help_request = ThingHelp()
            # Now see if we need to enhance it.
            if isinstance(self._help_request, ThingHelp):
                advanced = self._help_request.advanced or arg in self._HELP_ADVANCED_ARGS
                self._help_request = dataclasses.replace(self._help_request, advanced=advanced)
        return True

    def split_args(self, args: Sequence[str]) -> SplitArgs:
        """Split the specified arg list (or sys.argv if unspecified).

        args[0] is ignored.

        Returns a SplitArgs tuple.
        """
        goals: OrderedSet[str] = OrderedSet()
        scope_to_flags: DefaultDict[str, list[str]] = defaultdict(list)

        def add_scope(s: str) -> None:
            # Force the scope to appear, even if empty.
            if s not in scope_to_flags:
                scope_to_flags[s] = []

        specs: list[str] = []
        passthru: list[str] = []
        unknown_scopes: list[str] = []

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
            if not self._check_for_help_request(scope.lower()):
                add_scope(scope)
                if scope in self._known_goal_scopes:
                    goals.add(scope)
                else:
                    unknown_scopes.append(scope)
                for flag in flags:
                    assign_flag_to_scope(flag, scope)
            scope, flags = self._consume_scope()

        while self._unconsumed_args and not self._at_double_dash():
            arg = self._unconsumed_args.pop()
            if arg.startswith("-"):
                # We assume any args here are in global scope.
                if not self._check_for_help_request(arg):
                    assign_flag_to_scope(arg, GLOBAL_SCOPE)
            elif self.likely_a_spec(arg):
                specs.append(arg)
            elif arg not in self._known_scopes:
                unknown_scopes.append(arg)

        if self._at_double_dash():
            self._unconsumed_args.pop()
            passthru = list(reversed(self._unconsumed_args))

        if unknown_scopes and not self._help_request:
            self._help_request = UnknownGoalHelp(tuple(unknown_scopes))

        if not goals and not self._help_request:
            self._help_request = NoGoalHelp()

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

        if isinstance(self._help_request, ThingHelp):
            self._help_request = dataclasses.replace(
                self._help_request, things=tuple(goals) + tuple(unknown_scopes)
            )
        return SplitArgs(
            goals=list(goals),
            scope_to_flags=dict(scope_to_flags),
            specs=specs,
            passthru=passthru,
        )

    def likely_a_spec(self, arg: str) -> bool:
        """Return whether `arg` looks like a spec, rather than a goal name.

        An arg is a spec if it looks like an AddressSpec or a FilesystemSpec.
        """
        return (
            arg.startswith("!")
            or any(c in arg for c in (os.path.sep, ".", ":", "*", "#"))
            or os.path.exists(os.path.join(self._buildroot, arg))
        )

    def _consume_scope(self) -> tuple[str | None, list[str]]:
        """Returns a pair (scope, list of flags encountered in that scope).

        Note that the flag may be explicitly scoped, and therefore not actually belong to this scope.

        For example, in:

            ./pants --check-some-opt=100 check <target>

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
            if not self._check_for_help_request(flag):
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
        return (
            bool(self._unconsumed_args)
            and self._unconsumed_args[-1].startswith("-")
            and not self._at_double_dash()
        )

    def _at_scope(self) -> bool:
        return bool(self._unconsumed_args) and self._unconsumed_args[-1] in self._known_scopes

    def _at_double_dash(self) -> bool:
        return bool(self._unconsumed_args) and self._unconsumed_args[-1] == "--"
