# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

# TODO: Move these remaining classes elsewhere (probably in the help package), and
#  delete this file.


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
