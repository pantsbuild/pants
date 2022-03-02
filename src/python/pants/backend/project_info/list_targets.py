# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from typing import Dict, cast

from pants.engine.addresses import Address, Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.engine.target import DescriptionField, UnexpandedTargets
from pants.option.option_types import BoolOption

logger = logging.getLogger(__name__)


class ListSubsystem(LineOriented, GoalSubsystem):
    name = "list"
    help = "Lists all targets matching the file or target arguments."

    documented = BoolOption(
        "--documented",
        default=False,
        help="Print only targets that are documented with a description.",
    )


class List(Goal):
    subsystem_cls = ListSubsystem


@goal_rule
async def list_targets(
    addresses: Addresses, list_subsystem: ListSubsystem, console: Console
) -> List:
    if not addresses:
        logger.warning(f"No targets were matched in goal `{list_subsystem.name}`.")
        return List(exit_code=0)

    if list_subsystem.documented:
        # We must preserve target generators, not replace with their generated targets.
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
