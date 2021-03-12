# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import csv
import logging
from collections import defaultdict
from textwrap import fill, indent
from typing import cast

from pants.backend.project_info.dependees import Dependees, DependeesRequest
from pants.backend.python.target_types import InterpreterConstraintsField
from pants.backend.python.util_rules.pex import PexInterpreterConstraints
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.engine.addresses import Address, Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, Outputting
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import (
    RegisteredTargetTypes,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnexpandedTargets,
)
from pants.engine.unions import UnionMembership
from pants.python.python_setup import PythonSetup

logger = logging.getLogger(__name__)


class PyConstraintsSubsystem(Outputting, GoalSubsystem):
    name = "py-constraints"
    help = "Determine what Python interpreter constraints are used by files/targets."

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--summary",
            type=bool,
            default=False,
            help=(
                "Output a CSV summary of interpreter constraints for your whole repository. The "
                "headers are `Target`, `Constraints`, `Transitive Constraints`, `# Dependencies`, "
                "and `# Dependees`.\n\nThis information can be useful when prioritizing a "
                "migration from one Python version to another (e.g. to Python 3). Use "
                "`# Dependencies` and `# Dependees` to help prioritize which targets are easiest "
                "to port (low # dependencies) and highest impact to port (high # dependees).\n\n"
                "Use a tool like Pandas or Excel to process the CSV. Use the option "
                "`--py-constraints-output-file=summary.csv` to write directly to a file."
            ),
        )

    @property
    def summary(self) -> bool:
        return cast(bool, self.options.summary)


class PyConstraintsGoal(Goal):
    subsystem_cls = PyConstraintsSubsystem


@goal_rule
async def py_constraints(
    addresses: Addresses,
    console: Console,
    py_constraints_subsystem: PyConstraintsSubsystem,
    python_setup: PythonSetup,
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
) -> PyConstraintsGoal:
    if py_constraints_subsystem.summary:
        if addresses:
            console.print_stderr(
                "The `py-constraints --summary` goal does not take file/target arguments. Run "
                "`help py-constraints` for more details."
            )
            return PyConstraintsGoal(exit_code=1)

        all_expanded_targets, all_explicit_targets = await MultiGet(
            Get(Targets, AddressSpecs([DescendantAddresses("")])),
            Get(UnexpandedTargets, AddressSpecs([DescendantAddresses("")])),
        )
        all_python_targets = sorted(
            {
                t
                for t in (*all_expanded_targets, *all_explicit_targets)
                if t.has_field(InterpreterConstraintsField)
            },
            key=lambda tgt: cast(Address, tgt.address),
        )

        constraints_per_tgt = [
            PexInterpreterConstraints.create_from_targets([tgt], python_setup)
            for tgt in all_python_targets
        ]

        transitive_targets_per_tgt = await MultiGet(
            Get(TransitiveTargets, TransitiveTargetsRequest([tgt.address]))
            for tgt in all_python_targets
        )
        transitive_constraints_per_tgt = [
            PexInterpreterConstraints.create_from_targets(transitive_targets.closure, python_setup)
            for transitive_targets in transitive_targets_per_tgt
        ]

        dependees_per_root = await MultiGet(
            Get(Dependees, DependeesRequest([tgt.address], transitive=True, include_roots=False))
            for tgt in all_python_targets
        )

        data = [
            {
                "Target": tgt.address.spec,
                "Constraints": str(constraints),
                "Transitive Constraints": str(transitive_constraints),
                "# Dependencies": len(transitive_targets.dependencies),
                "# Dependees": len(dependees),
            }
            for tgt, constraints, transitive_constraints, transitive_targets, dependees in zip(
                all_python_targets,
                constraints_per_tgt,
                transitive_constraints_per_tgt,
                transitive_targets_per_tgt,
                dependees_per_root,
            )
        ]

        with py_constraints_subsystem.output_sink(console) as stdout:
            writer = csv.DictWriter(
                stdout,
                fieldnames=[
                    "Target",
                    "Constraints",
                    "Transitive Constraints",
                    "# Dependencies",
                    "# Dependees",
                ],
            )
            writer.writeheader()
            for entry in data:
                writer.writerow(entry)

        return PyConstraintsGoal(exit_code=0)

    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(addresses))
    final_constraints = PexInterpreterConstraints.create_from_targets(
        transitive_targets.closure, python_setup
    )

    if not final_constraints:
        target_types_with_constraints = sorted(
            tgt_type.alias
            for tgt_type in registered_target_types.types
            if tgt_type.class_has_field(InterpreterConstraintsField, union_membership)
        )
        logger.warning(
            "No Python files/targets matched for the `py-constraints` goal. All target types with "
            f"Python interpreter constraints: {', '.join(target_types_with_constraints)}"
        )
        return PyConstraintsGoal(exit_code=0)

    constraints_to_addresses = defaultdict(set)
    for tgt in transitive_targets.closure:
        constraints = PexInterpreterConstraints.create_from_targets([tgt], python_setup)
        if not constraints:
            continue
        constraints_to_addresses[constraints].add(tgt.address)

    with py_constraints_subsystem.output(console) as output_stdout:
        output_stdout(f"Final merged constraints: {final_constraints}\n")
        if len(addresses) > 1:
            merged_constraints_warning = (
                "(These are the constraints used if you were to depend on all of the input "
                "files/targets together, even though they may end up never being used together in "
                "the real world. Consider using a more precise query or running "
                "`./pants py-constraints --summary`.)\n"
            )
            output_stdout(indent(fill(merged_constraints_warning, 80), "  "))

        for constraint, addrs in sorted(constraints_to_addresses.items()):
            output_stdout(f"\n{constraint}\n")
            for addr in sorted(addrs):
                output_stdout(f"  {addr}\n")

    return PyConstraintsGoal(exit_code=0)


def rules():
    return collect_rules()
