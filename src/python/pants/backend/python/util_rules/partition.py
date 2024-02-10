# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from collections import defaultdict
from typing import Iterable, Mapping, Protocol, Sequence, TypeVar

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import InterpreterConstraintsField, PythonResolveField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.engine.rules import Get
from pants.engine.target import AllTargets, FieldSet
from pants.util.ordered_set import OrderedSet

ResolveName = str


class _FieldSetWithResolveAndICs(Protocol):
    @property
    def resolve(self) -> PythonResolveField:
        ...

    @property
    def interpreter_constraints(self) -> InterpreterConstraintsField:
        ...


_FS = TypeVar("_FS", bound=_FieldSetWithResolveAndICs)


def _partition_by_interpreter_constraints_and_resolve(
    field_sets: Sequence[_FS],
    python_setup: PythonSetup,
) -> Mapping[tuple[ResolveName, InterpreterConstraints], OrderedSet[_FS]]:
    resolve_and_interpreter_constraints_to_field_sets: Mapping[
        tuple[str, InterpreterConstraints], OrderedSet[_FS]
    ] = defaultdict(lambda: OrderedSet())
    for field_set in field_sets:
        resolve = field_set.resolve.normalized_value(python_setup)
        interpreter_constraints = InterpreterConstraints.create_from_compatibility_fields(
            [field_set.interpreter_constraints], python_setup
        )
        resolve_and_interpreter_constraints_to_field_sets[(resolve, interpreter_constraints)].add(
            field_set
        )

    return resolve_and_interpreter_constraints_to_field_sets


async def _find_all_unique_interpreter_constraints(
    python_setup: PythonSetup,
    field_set_type: type[FieldSet],
    *,
    extra_constraints_per_tgt: Iterable[InterpreterConstraintsField] = (),
) -> InterpreterConstraints:
    """Find all unique interpreter constraints used by given field set.

    This will find the constraints for each individual matching field set, and then OR across all
    unique constraints. Usually, Pants partitions when necessary so that conflicting interpreter
    constraints can be handled gracefully. But in some cases, like the `generate-lockfiles` goal, we
    need to combine those targets into a single value. This ORs, so that if you have a ==2.7
    partition and ==3.6 partition, for example, we return ==2.7 OR ==3.6.

    Returns the global interpreter constraints if no relevant targets were matched.
    """
    all_tgts = await Get(AllTargets)
    unique_constraints = {
        InterpreterConstraints.create_from_compatibility_fields(
            [tgt[InterpreterConstraintsField], *extra_constraints_per_tgt], python_setup
        )
        for tgt in all_tgts
        if tgt.has_field(InterpreterConstraintsField) and field_set_type.is_applicable(tgt)
    }
    if not unique_constraints and extra_constraints_per_tgt:
        unique_constraints.add(
            InterpreterConstraints.create_from_compatibility_fields(
                extra_constraints_per_tgt,
                python_setup,
            )
        )
    constraints = InterpreterConstraints(
        itertools.chain.from_iterable(ic for ic in unique_constraints if ic)
    )
    return constraints or InterpreterConstraints(python_setup.interpreter_constraints)
