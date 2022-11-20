# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.subsystems.gotest import GoTestSubsystem
from pants.backend.go.target_types import (
    GoCgoEnabledField,
    GoRaceDetectorEnabledField,
    GoTestRaceDetectorEnabledField,
)
from pants.backend.go.util_rules import go_mod
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

    # Enable the Go data race detector is true.
    with_race_detector: bool = False


@dataclass(frozen=True)
class GoBuildOptionsFromTargetRequest(EngineAwareParameter):
    address: Address
    for_tests: bool = False

    def debug_hint(self) -> str | None:
        return self.address.spec


@dataclass(frozen=True)
class GoBuildOptionsFieldSet(FieldSet):
    required_fields = (GoCgoEnabledField,)

    cgo_enabled: GoCgoEnabledField
    race: GoRaceDetectorEnabledField


@dataclass(frozen=True)
class GoTestBuildOptionsFieldSet(FieldSet):
    required_fields = (GoTestRaceDetectorEnabledField,)

    test_race: GoTestRaceDetectorEnabledField


def _first_non_none_value(items: Iterable[bool | None]) -> bool:
    """Return the first non-None value from the iterator."""
    for item in items:
        if item is not None:
            return item
    return False


@rule
async def go_extract_build_options_from_target(
    request: GoBuildOptionsFromTargetRequest,
    golang: GolangSubsystem,
    go_test_subsystem: GoTestSubsystem,
) -> GoBuildOptions:
    wrapped_target = await Get(
        WrappedTarget,
        WrappedTargetRequest(
            request.address, description_of_origin="the `go_extract_build_options_from_target` rule"
        ),
    )
    target = wrapped_target.target
    target_fields: GoBuildOptionsFieldSet | None = None
    if GoBuildOptionsFieldSet.is_applicable(target):
        target_fields = GoBuildOptionsFieldSet.create(target)

    test_target_fields: GoTestBuildOptionsFieldSet | None = None
    if request.for_tests and GoTestBuildOptionsFieldSet.is_applicable(target):
        test_target_fields = GoTestBuildOptionsFieldSet.create(target)

    # Find the owning `go_mod` target so any unspecified fields on a target like `go_binary` will then
    # fallback to the `go_mod`. If the target does not have build option fields, then only the `go_mod`
    # will be used.
    owning_go_mod = await Get(OwningGoMod, OwningGoModRequest(request.address))
    wrapped_target_go_mod = await Get(
        WrappedTarget,
        WrappedTargetRequest(
            owning_go_mod.address,
            description_of_origin="the `go_extract_build_options_from_target` rule",
        ),
    )
    go_mod_target = wrapped_target_go_mod.target
    go_mod_target_fields = GoBuildOptionsFieldSet.create(go_mod_target)

    # Extract the `cgo_enabled` value for this target.
    cgo_enabled: bool | None = None
    if target_fields is not None:
        if target_fields.cgo_enabled.value is not None:
            cgo_enabled = target_fields.cgo_enabled.value
    if cgo_enabled is None:
        if go_mod_target_fields.cgo_enabled.value is not None:
            cgo_enabled = go_mod_target_fields.cgo_enabled.value
    if cgo_enabled is None:
        cgo_enabled = golang.cgo_enabled

    # Extract the `with_race_detector` value for this target.
    with_race_detector = _first_non_none_value(
        [
            True if go_test_subsystem.force_race and test_target_fields else None,
            test_target_fields.test_race.value if test_target_fields else None,
            target_fields.race.value if target_fields else None,
            go_mod_target_fields.race.value if go_mod_target_fields else None,
            False,
        ]
    )

    return GoBuildOptions(
        cgo_enabled=cgo_enabled,
        with_race_detector=with_race_detector,
    )


def rules():
    return (
        *collect_rules(),
        *go_mod.rules(),
        *graph.rules(),
    )
