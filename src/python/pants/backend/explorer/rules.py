# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.target_types import PythonDistributionDependenciesField
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    FieldSet,
    Target,
    TransitiveTargets,
    TransitiveTargetsRequest,
    ValidatedDependencies,
    ValidateDependenciesRequest,
)
from pants.engine.unions import UnionRule

_EXPLORER_BACKEND_PATH = "/pants/backend/explorer"


@dataclass(frozen=True)
class ExplorerDependencyValidationFieldSet(FieldSet):
    """Validate that the explorer modules are only ever imported from within the explorer backend,
    to isolate the 3rdparty dependencies that comes with that backend, so it doesn't leak into the
    core Pants distribution."""

    required_fields = (PythonDistributionDependenciesField,)

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        # Do not validate modules within the explorer backend.
        return _EXPLORER_BACKEND_PATH in tgt.address.spec_path


class ExplorerValidateDependenciesRequest(ValidateDependenciesRequest):
    field_set_type = ExplorerDependencyValidationFieldSet


@rule
async def validate_explorer_dependencies(
    request: ExplorerValidateDependenciesRequest,
) -> ValidatedDependencies:
    targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.dependencies))
    for tgt in targets.closure:
        assert (
            _EXPLORER_BACKEND_PATH not in tgt.address.spec_path
        ), f"{request.field_set.address} must not have a dependency on {tgt.address}."
    return ValidatedDependencies()


def rules():
    return (
        *collect_rules(),
        UnionRule(ValidateDependenciesRequest, ExplorerValidateDependenciesRequest),
    )
