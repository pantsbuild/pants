# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from abc import ABCMeta
from dataclasses import dataclass
from itertools import chain

from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import Effect, Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import (
    FieldSet,
    NoApplicableTargetsBehavior,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionMembership, union
from pants.option.custom_types import shell_str

logger = logging.getLogger(__name__)


@union
@dataclass(frozen=True)
class InstallFieldSet(FieldSet, metaclass=ABCMeta):
    """The FieldSet type for the `install` goal."""


@dataclass(frozen=True)
class InstallProcess:
    """Individual process to run in the given order to perform the installation."""

    name: str
    description: str | None = None
    process: InteractiveProcess | None = None


class InstallProcesses(Collection[InstallProcess]):
    """Collection of what processes to run for all built packages."""


class InstallSubsystem(GoalSubsystem):
    name = "experimental-install"
    help = "Perform an install process"

    @classmethod
    def activated(cls, union_memebership: UnionMembership) -> bool:
        return InstallFieldSet in union_memebership

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help="Arguments to pass to the underlying tool",
        )


@dataclass(frozen=True)
class Install(Goal):
    subsystem_cls = InstallSubsystem


@goal_rule
async def run_deploy(console: Console, install_subsystem: InstallSubsystem) -> Install:
    targets_to_valid_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            InstallFieldSet,
            goal_description=f"the {install_subsystem.name} goal",
            no_applicable_targets_behavior=NoApplicableTargetsBehavior.warn,
        ),
    )

    if not targets_to_valid_field_sets.field_sets:
        return Install(exit_code=0)

    processes = await MultiGet(
        Get(InstallProcesses, InstallFieldSet, field_set)
        for field_set in targets_to_valid_field_sets.field_sets
    )

    # Run all processes
    exit_code: int = 0
    results: list[str] = []

    for install in chain.from_iterable(processes):
        if not install.process:
            sigil = console.sigil_skipped()
            status = "skipped"
            if install.description:
                status += f" {install.description}"
            results.append(f"{sigil} {install.name} {status}.")
            continue

        logger.info(f"Starting installation of: {install.name}")
        res = await Effect(InteractiveProcessResult, InteractiveProcess, install.process)
        if res.exit_code == 0:
            sigil = console.sigil_succeeded()
            status = "installed"
            prep = "to"
        else:
            sigil = console.sigil_failed()
            status = "failed"
            prep = "for"
            exit_code = res.exit_code

        if install.description:
            status += f" {prep} {install.description}"
        results.append(f"{sigil} {install.name} {status}.")

    console.print_stderr("")
    if not results:
        sigil = console.sigil_skipped()
        console.print_stderr(f"{sigil} Nothing installed.")

    for line in results:
        console.print_stderr(line)

    return Install(exit_code)


def rules():
    return collect_rules()
