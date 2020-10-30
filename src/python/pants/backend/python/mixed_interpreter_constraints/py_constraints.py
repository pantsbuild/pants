# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from collections import defaultdict
from textwrap import fill, indent

from pants.backend.python.util_rules.pex import PexInterpreterConstraints
from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.python.python_setup import PythonSetup

logger = logging.getLogger(__name__)


class PyConstraintsSubsystem(GoalSubsystem):
    """Determine what Python interpreter constraints are used by files/targets."""

    name = "py-constraints"


class PyConstraintsGoal(Goal):
    subsystem_cls = PyConstraintsSubsystem


@goal_rule
async def py_constraints(
    addresses: Addresses, console: Console, python_setup: PythonSetup
) -> PyConstraintsGoal:
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(addresses))
    final_constraints = PexInterpreterConstraints.create_from_targets(
        transitive_targets.closure, python_setup
    )

    if not final_constraints:
        logger.warning("No Python files/targets matched for the `py-constraints` goal.")
        return PyConstraintsGoal(exit_code=0)

    console.print_stdout(f"Final merged constraints: {final_constraints}")
    if len(addresses) > 1:
        merged_constraints_warning = (
            "(These are the constraints used if you were to depend on all of the input "
            "files/targets together, even though they may end up never being used together in the "
            "real world. Consider using a more precise query.)"
        )
        console.print_stdout(indent(fill(merged_constraints_warning, 80), "  "))

    constraints_to_addresses = defaultdict(set)
    for tgt in transitive_targets.closure:
        constraints = PexInterpreterConstraints.create_from_targets([tgt], python_setup)
        if not constraints:
            continue
        constraints_to_addresses[constraints].add(tgt.address)

    for constraint, addrs in sorted(constraints_to_addresses.items()):
        console.print_stdout(f"\n{constraint}")
        for addr in sorted(addrs):
            console.print_stdout(f"  {addr}")

    return PyConstraintsGoal(exit_code=0)


def rules():
    return collect_rules()
