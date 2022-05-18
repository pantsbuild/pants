# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping, TypeVar

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.engine.rules import Get, rule_helper
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, CoarsenedTargetsRequest, FieldSet
from pants.util.ordered_set import OrderedSet

ResolveName = str

FS = TypeVar("FS", bound=FieldSet)


@rule_helper
async def _by_interpreter_constraints_and_resolve(
    field_sets: Iterable[FS],
    python_setup: PythonSetup,
) -> Mapping[
    tuple[ResolveName, InterpreterConstraints],
    tuple[OrderedSet[FS], OrderedSet[CoarsenedTarget]],
]:
    coarsened_targets = await Get(
        CoarsenedTargets,
        CoarsenedTargetsRequest(
            (field_set.address for field_set in field_sets), expanded_targets=True
        ),
    )
    coarsened_targets_by_address = coarsened_targets.by_address()

    resolve_and_interpreter_constraints_to_coarsened_targets: Mapping[
        tuple[str, InterpreterConstraints],
        tuple[OrderedSet[FS], OrderedSet[CoarsenedTarget]],
    ] = defaultdict(lambda: (OrderedSet(), OrderedSet()))
    for root in field_sets:
        ct = coarsened_targets_by_address[root.address]
        # If there is a cycle in the roots, we still only take the first resolve, as the other
        # members will be validated when the partition is actually built.
        resolve = ct.representative[PythonResolveField].normalized_value(python_setup)
        interpreter_constraints = InterpreterConstraints.create_from_targets(
            ct.members, python_setup
        )
        # If a CoarsenedTarget did not have IntepreterConstraints, then it's because it didn't
        # contain any targets with the field, and so there is no point checking it.
        if interpreter_constraints is None:
            continue

        roots, root_cts = resolve_and_interpreter_constraints_to_coarsened_targets[
            (resolve, interpreter_constraints)
        ]
        roots.add(root)
        root_cts.add(ct)

    return resolve_and_interpreter_constraints_to_coarsened_targets
