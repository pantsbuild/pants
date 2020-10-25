# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import os.path
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.util.ordered_set import OrderedSet


class ArgSplitterError(Exception):
    pass


@dataclass(frozen=True)
class SplitArgs:
    """The result of splitting args."""

    goals: List[str]  # Explicitly requested goals.
    scope_to_flags: Dict[str, List[str]]  # Scope name -> list of flags in that scope.
    specs: List[str]  # The specifications for what to run against, e.g. the targets or files
    passthru: List[str]  # Any remaining args specified after a -- separator.


class HelpRequest(ABC):
    """Represents an implicit or explicit request for help by the user."""


@dataclass(frozen=True)
class ThingHelp(HelpRequest):
    """The user requested help on one or more things: e.g., an options scope or a target type."""

    advanced: bool = False
    things: Tuple[str, ...] = ()


class VersionHelp(HelpRequest):
    """The user asked for the version of this instance of pants."""


class AllHelp(HelpRequest):
    """The user requested a dump of all help info."""


@dataclass(frozen=True)
class UnknownGoalHelp(HelpRequest):
    """The user specified an unknown goal (or task)."""

    unknown_goals: Tuple[str, ...]


class NoGoalHelp(HelpRequest):
    """The user specified no goals."""


class ArgSplitter:
    """Splits a command-line into scoped sets of flags and a set of specs.

    Recognizes, e.g.:

    ./pants goal -x compile --foo compile.java -y target1 target2
    ./pants -x compile --foo compile.java -y -- target1 target2
    ./pants -x compile target1 target2 --compile-java-flag
    ./pants -x --compile-java-flag compile target1 target2

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
        self._buildroot = Path(buildroot)
        self._known_scope_infos = known_scope_infos
        self._known_scopes = {si.scope for si in known_scope_infos} | {
            "version",
            "help",
            "help-advanced",
            "help-all",
        }
        self._unconsumed_args: List[
            str
        ] = []  # In reverse order, for efficient popping off the end.
        self._help_request: Optional[
            HelpRequest
        ] = None  # Will be set if we encounter any help flags.

        # For convenience, and for historical reasons, we allow --scope-flag-name anywhere on the
        # cmd line, as an alternative to ... scope --flag-name.

        # We check for prefixes in reverse order, so we match the longest prefix first.
        sorted_scope_infos = sorted(
            [si for si in self._known_scope_infos if si.scope],
            key=lambda si: si.scope,
            reverse=True,
        )

        # List of pairs (prefix, ScopeInfo).
        self._known_scoping_prefixes = [
            (f"{si.scope.replace('.', '-')}-", si) for si in sorted_scope_infos
        ]

    @property
    def help_request(self) -> Optional[HelpRequest]:
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
        scope_to_flags: Dict[str, List[str]] = {}

        def add_scope(s: str) -> None:
            # Force the scope to appear, even if empty.
            if s not in scope_to_flags:
                scope_to_flags[s] = []

        specs: List[str] = []
        passthru: List[str] = []
        unknown_scopes: List[str] = []

        self._unconsumed_args = list(reversed(args))
        # The first token is the binary name, so skip it.
        self._unconsumed_args.pop()

        def assign_flag_to_scope(flg: str, default_scope: str) -> None:
            flag_scope, descoped_flag = self._descope_flag(flg, default_scope=default_scope)
            if flag_scope not in scope_to_flags:
                scope_to_flags[flag_scope] = []
            scope_to_flags[flag_scope].append(descoped_flag)

        global_flags = self._consume_flags()

        add_scope(GLOBAL_SCOPE)
        for flag in global_flags:
            assign_flag_to_scope(flag, GLOBAL_SCOPE)
        scope, flags = self._consume_scope()
        while scope:
            if not self._check_for_help_request(scope.lower()):
                add_scope(scope)
                goals.add(scope.partition(".")[0])
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

        if isinstance(self._help_request, ThingHelp):
            self._help_request = dataclasses.replace(
                self._help_request, things=tuple(goals) + tuple(unknown_scopes)
            )
        return SplitArgs(
            goals=list(goals),
            scope_to_flags=scope_to_flags,
            specs=specs,
            passthru=passthru,
        )

    def likely_a_spec(self, arg: str) -> bool:
        """Return whether `arg` looks like a spec, rather than a goal name.

        An arg is a spec if it looks like an AddressSpec or a FilesystemSpec. In the future we can
        expand this heuristic to support other kinds of specs, such as URLs.
        """
        return (
            any(symbol in arg for symbol in (os.path.sep, ":", "*"))
            or arg.startswith("!")
            or (self._buildroot / arg).exists()
        )

    def _consume_scope(self) -> Tuple[Optional[str], List[str]]:
        """Returns a pair (scope, list of flags encountered in that scope).

        Note that the flag may be explicitly scoped, and therefore not actually belong to this scope.

        For example, in:

        ./pants --compile-java-partition-size-hint=100 compile <target>

        --compile-java-partition-size-hint should be treated as if it were --partition-size-hint=100
        in the compile.java scope.
        """
        if not self._at_scope():
            return None, []
        scope = self._unconsumed_args.pop()
        flags = self._consume_flags()
        return scope, flags

    def _consume_flags(self) -> List[str]:
        """Read flags until we encounter the first token that isn't a flag."""
        flags = []
        while self._at_flag():
            flag = self._unconsumed_args.pop()
            if not self._check_for_help_request(flag):
                flags.append(flag)
        return flags

    def _descope_flag(self, flag: str, default_scope: str) -> Tuple[str, str]:
        """If the flag is prefixed by its scope, in the old style, extract the scope.

        Otherwise assume it belongs to default_scope.

        returns a pair (scope, flag).
        """
        for scope_prefix, scope_info in self._known_scoping_prefixes:
            for flag_prefix in ["--", "--no-"]:
                prefix = flag_prefix + scope_prefix
                if flag.startswith(prefix):
                    scope = scope_info.scope
                    if scope != GLOBAL_SCOPE and default_scope != GLOBAL_SCOPE:
                        # We allow goal.task --subsystem-foo to refer to the task-level subsystem instance,
                        # i.e., as if qualified by --subsystem-goal-task-foo.
                        # Note that this means that we can't set a task option on the cmd-line if its
                        # name happens to start with a subsystem scope.
                        # TODO: Either fix this or at least detect such options and warn.
                        task_subsystem_scope = f"{scope_info.scope}.{default_scope}"
                        if (
                            task_subsystem_scope in self._known_scopes
                        ):  # Such a task subsystem actually exists.
                            scope = task_subsystem_scope
                    return scope, flag_prefix + flag[len(prefix) :]
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
