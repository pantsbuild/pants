# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import goal_rule


class ListAndDieForTestingOptions(GoalSubsystem):
    """A fast and deadly variant of `./pants list`."""

    name = "list-and-die-for-testing"


class ListAndDieForTesting(Goal):
    subsystem_cls = ListAndDieForTestingOptions


@goal_rule
def fast_list_and_die_for_testing(console: Console, addresses: Addresses) -> ListAndDieForTesting:
    for address in addresses:
        console.print_stdout(address.spec)
    return ListAndDieForTesting(exit_code=42)


def rules():
    return [
        fast_list_and_die_for_testing,
    ]
