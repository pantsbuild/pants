# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict, cast

from pants.engine.addresses import Address, Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.engine.target import DescriptionField, ProvidesField, UnexpandedTargets


class ListSubsystem(LineOriented, GoalSubsystem):
    """Lists all targets matching the file or target arguments."""

    name = "list"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--provides",
            type=bool,
            default=False,
            help=(
                "List only targets that provide an artifact, displaying the columns specified by "
                "--provides-columns."
            ),
        )
        register(
            "--documented",
            type=bool,
            default=False,
            help="Print only targets that are documented with a description.",
        )

    @property
    def provides(self) -> bool:
        return cast(bool, self.options.provides)

    @property
    def documented(self) -> bool:
        return cast(bool, self.options.documented)


class List(Goal):
    subsystem_cls = ListSubsystem


@goal_rule
async def list_targets(
    addresses: Addresses, list_subsystem: ListSubsystem, console: Console
) -> List:
    if not addresses:
        console.print_stderr(f"WARNING: No targets were matched in goal `{list_subsystem.name}`.")
        return List(exit_code=0)

    if list_subsystem.provides and list_subsystem.documented:
        raise ValueError(
            "Cannot specify both `--list-documented` and `--list-provides` at the same time. "
            "Please choose one."
        )

    if list_subsystem.provides:
        targets = await Get(UnexpandedTargets, Addresses, addresses)
        addresses_with_provide_artifacts = {
            tgt.address: tgt[ProvidesField].value
            for tgt in targets
            if tgt.get(ProvidesField).value is not None
        }
        with list_subsystem.line_oriented(console) as print_stdout:
            for address, artifact in addresses_with_provide_artifacts.items():
                print_stdout(f"{address.spec} {artifact}")
        return List(exit_code=0)

    if list_subsystem.documented:
        targets = await Get(UnexpandedTargets, Addresses, addresses)
        addresses_with_descriptions = cast(
            Dict[Address, str],
            {
                tgt.address: tgt[DescriptionField].value
                for tgt in targets
                if tgt.get(DescriptionField).value is not None
            },
        )
        with list_subsystem.line_oriented(console) as print_stdout:
            for address, description in addresses_with_descriptions.items():
                formatted_description = "\n  ".join(description.strip().split("\n"))
                print_stdout(f"{address.spec}\n  {formatted_description}")
        return List(exit_code=0)

    with list_subsystem.line_oriented(console) as print_stdout:
        for address in sorted(addresses):
            print_stdout(address.spec)
    return List(exit_code=0)


def rules():
    return collect_rules()
