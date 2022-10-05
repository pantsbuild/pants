# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.target_types import GoCgoEnabledField
from pants.backend.go.util_rules.go_mod import OwningGoMod, OwningGoModRequest
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals import graph
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, WrappedTarget, WrappedTargetRequest


@dataclass(frozen=True)
class GoBuildOptions:
    # Controls whether cgo support is enabled.
    cgo_enabled: bool = True


@dataclass(frozen=True)
class GoBuildOptionsFromTargetRequest(EngineAwareParameter):
    address: Address

    def debug_hint(self) -> str | None:
        return self.address.spec


@dataclass(frozen=True)
class GoBuildOptionsFieldSet(FieldSet):
    required_fields = (GoCgoEnabledField,)

    cgo_enabled: GoCgoEnabledField


@rule
async def go_extract_build_options_from_target(
    request: GoBuildOptionsFromTargetRequest, golang: GolangSubsystem
) -> GoBuildOptions:
    wrapped_target = await Get(
        WrappedTarget,
        WrappedTargetRequest(
            request.address, description_of_origin="the `go_extract_build_options_from_target` rule"
        ),
    )
    target = wrapped_target.target

    # If this target does not have build option fields, then find the owning `go_mod` target and
    # use its fields.
    if not GoBuildOptionsFieldSet.is_applicable(target):
        owning_go_mod = await Get(OwningGoMod, OwningGoModRequest(request.address))
        wrapped_target_go_mod = await Get(
            WrappedTarget,
            WrappedTargetRequest(
                owning_go_mod.address,
                description_of_origin="the `go_extract_build_options_from_target` rule",
            ),
        )
        target = wrapped_target_go_mod.target

    opts_field_set = GoBuildOptionsFieldSet.create(target)

    cgo_enabled: bool | None = None
    if opts_field_set.cgo_enabled.value is not None:
        cgo_enabled = opts_field_set.cgo_enabled.value
    if cgo_enabled is None:
        cgo_enabled = golang.cgo_enabled

    return GoBuildOptions(
        cgo_enabled=cgo_enabled,
    )


def rules():
    return (
        *collect_rules(),
        *graph.rules(),
    )
