# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.subsystems.gotest import GoTestSubsystem
from pants.backend.go.target_types import (
    GoCgoEnabledField,
    GoMemorySanitizerEnabledField,
    GoRaceDetectorEnabledField,
    GoTestMemorySanitizerEnabledField,
    GoTestRaceDetectorEnabledField,
)
from pants.backend.go.util_rules import go_mod, goroot
from pants.backend.go.util_rules.go_mod import OwningGoMod, OwningGoModRequest
from pants.backend.go.util_rules.goroot import GoRoot
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals import graph
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, WrappedTarget, WrappedTargetRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoBuildOptions:
    # Controls whether cgo support is enabled.
    cgo_enabled: bool = True

    # Enable the Go data race detector is true.
    with_race_detector: bool = False

    # Enable interoperation with the LLVM memory sanitizer.
    with_msan: bool = False


@dataclass(frozen=True)
class GoBuildOptionsFromTargetRequest(EngineAwareParameter):
    address: Address
    for_tests: bool = False

    def debug_hint(self) -> str | None:
        return self.address.spec


@dataclass(frozen=True)
class GoBuildOptionsFieldSet(FieldSet):
    required_fields = (GoCgoEnabledField, GoRaceDetectorEnabledField, GoMemorySanitizerEnabledField)

    cgo_enabled: GoCgoEnabledField
    race: GoRaceDetectorEnabledField
    msan: GoMemorySanitizerEnabledField


@dataclass(frozen=True)
class GoTestBuildOptionsFieldSet(FieldSet):
    required_fields = (GoTestRaceDetectorEnabledField, GoTestMemorySanitizerEnabledField)

    test_race: GoTestRaceDetectorEnabledField
    test_msan: GoTestMemorySanitizerEnabledField


def _first_non_none_value(items: Iterable[tuple[bool | None, str] | None]) -> tuple[bool, str]:
    """Return the first non-None value from the iterator."""
    for item_opt in items:
        if item_opt is not None:
            item, reason = item_opt
            if item is not None:
                return item, reason
    return False, "default"


# Adapted from https://github.com/golang/go/blob/920f87adda5412a41036a862cf2139bed24aa533/src/internal/platform/supported.go#L7-L23.
def race_detector_supported(goroot: GoRoot) -> bool:
    """Returns True if the Go data race detector is supported for the `goroot`'s platform."""
    if goroot.goos == "linux":
        return goroot.goarch in ("amd64", "ppc64le", "arm64", "s390x")
    elif goroot.goos == "darwin":
        return goroot.goarch in ("amd64", "arm64")
    elif goroot.goos in ("freebsd", "netbsd", "openbsd", "windows"):
        return goroot.goarch == "amd64"
    else:
        return False


# Adapted from https://github.com/golang/go/blob/920f87adda5412a41036a862cf2139bed24aa533/src/internal/platform/supported.go#L25-L37
def msan_supported(goroot: GoRoot) -> bool:
    """Returns True if this platform supports interoperation with the LLVM memory sanitizer."""
    if goroot.goos == "linux":
        return goroot.goarch in ("amd64", "arm64")
    elif goroot.goos == "freebsd":
        return goroot.goarch == "amd64"
    else:
        return False


@rule
async def go_extract_build_options_from_target(
    request: GoBuildOptionsFromTargetRequest,
    goroot: GoRoot,
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
    with_race_detector, race_detector_reason = _first_non_none_value(
        [
            (
                True if go_test_subsystem.force_race and test_target_fields else None,
                "the `[go-test].force_race` option is in effect",
            ),
            (
                test_target_fields.test_race.value,
                f"{GoTestRaceDetectorEnabledField.alias}={test_target_fields.test_race.value} on target `{request.address}`",
            )
            if test_target_fields
            else None,
            (
                target_fields.race.value,
                f"{GoRaceDetectorEnabledField.alias}={target_fields.race.value} on target `{request.address}`",
            )
            if target_fields
            else None,
            (
                go_mod_target_fields.race.value,
                f"{GoRaceDetectorEnabledField.alias}={go_mod_target_fields.race.value} on target `{request.address}`",
            )
            if go_mod_target_fields
            else None,
            (False, "default"),
        ]
    )
    if with_race_detector and not race_detector_supported(goroot):
        logger.warning(
            f"The Go data race detector would have been enabled for target `{request.address}, "
            f"but the race detector is not supported on platform {goroot.goos}/{goroot.goarch}."
        )
        with_race_detector = False

    # Extract the `with_msan` value for this target.
    with_msan, msan_reason = _first_non_none_value(
        [
            (
                True if go_test_subsystem.force_msan and test_target_fields else None,
                "the `[go-test].force_msan` option is in effect",
            ),
            (
                test_target_fields.test_msan.value,
                f"{GoTestMemorySanitizerEnabledField.alias}={test_target_fields.test_msan.value} on target `{request.address}`",
            )
            if test_target_fields
            else None,
            (
                target_fields.msan.value,
                f"{GoMemorySanitizerEnabledField.alias}={target_fields.msan.value} on target `{request.address}`",
            )
            if target_fields
            else None,
            (
                go_mod_target_fields.msan.value,
                f"{GoMemorySanitizerEnabledField.alias}={go_mod_target_fields.msan.value} on target `{request.address}`",
            )
            if go_mod_target_fields
            else None,
            (False, "default"),
        ]
    )
    if with_msan and not msan_supported(goroot):
        logger.warning(
            f"Interoperation with the LLVM memory sanitizer would have been enabled for target `{request.address}, "
            f"but the memory sanitizer is not supported on platform {goroot.goos}/{goroot.goarch}."
        )
        with_msan = False

    if with_race_detector and with_msan:
        raise ValueError(
            "The Go race detector and msan support cannot be enabled at the same time. "
            f"The race detector is enabled because {race_detector_reason} "
            f"and msan support is enabled because {msan_reason}."
        )

    return GoBuildOptions(
        cgo_enabled=cgo_enabled,
        with_race_detector=with_race_detector,
        with_msan=with_msan,
    )


def rules():
    return (
        *collect_rules(),
        *go_mod.rules(),
        *goroot.rules(),
        *graph.rules(),
    )
