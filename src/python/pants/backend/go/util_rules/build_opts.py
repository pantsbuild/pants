# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.subsystems.gotest import GoTestSubsystem
from pants.backend.go.target_types import (
    GoAddressSanitizerEnabledField,
    GoAssemblerFlagsField,
    GoCgoEnabledField,
    GoCompilerFlagsField,
    GoLinkerFlagsField,
    GoMemorySanitizerEnabledField,
    GoRaceDetectorEnabledField,
    GoTestAddressSanitizerEnabledField,
    GoTestMemorySanitizerEnabledField,
    GoTestRaceDetectorEnabledField,
)
from pants.backend.go.util_rules import go_mod, goroot
from pants.backend.go.util_rules.coverage import GoCoverageConfig
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
    # Coverage configuration.
    # If this is set and a package's import path matches `import_path_include_patterns`, then the package
    # will be instrumented for code coverage. (A caller can also force code coverage instrumentation by setting
    # `with_coverage` to `True` on `BuildGoPackageTargetRequest`.)
    coverage_config: GoCoverageConfig | None = None

    # Controls whether cgo support is enabled.
    cgo_enabled: bool = True

    # Enable the Go data race detector is true.
    with_race_detector: bool = False

    # Enable interoperation with the C/C++ memory sanitizer.
    with_msan: bool = False

    # Enable interoperation with the C/C++ address sanitizer.
    with_asan: bool = False

    # Extra flags to pass to the Go compiler (i.e., `go tool compile`).
    # Note: These flags come from `go_mod` and `go_binary` targets. Package-specific compiler flags
    # may still come from `go_package` targets.
    compiler_flags: tuple[str, ...] = ()

    # Extra flags to pass to the Go linker (i.e., `go tool link`).
    # Note: These flags come from `go_mod` and `go_binary` targets.
    linker_flags: tuple[str, ...] = ()

    # Extra flags to pass to the Go assembler (i.e., `go tool asm`).
    # Note: These flags come from `go_mod` and `go_binary` targets. Package-specific assembler flags
    # may still come from `go_package` targets.
    assembler_flags: tuple[str, ...] = ()

    def __post_init__(self):
        assert not (self.with_race_detector and self.with_msan)
        assert not (self.with_race_detector and self.with_asan)
        assert not (self.with_msan and self.with_asan)


@dataclass(frozen=True)
class GoBuildOptionsFromTargetRequest(EngineAwareParameter):
    address: Address
    for_tests: bool = False

    def debug_hint(self) -> str | None:
        return self.address.spec


@dataclass(frozen=True)
class GoBuildOptionsFieldSet(FieldSet):
    required_fields = (
        GoCgoEnabledField,
        GoRaceDetectorEnabledField,
        GoMemorySanitizerEnabledField,
        GoAddressSanitizerEnabledField,
        GoCompilerFlagsField,
        GoLinkerFlagsField,
    )

    cgo_enabled: GoCgoEnabledField
    race: GoRaceDetectorEnabledField
    msan: GoMemorySanitizerEnabledField
    asan: GoAddressSanitizerEnabledField
    compiler_flags: GoCompilerFlagsField
    linker_flags: GoLinkerFlagsField
    assembler_flags: GoAssemblerFlagsField


@dataclass(frozen=True)
class GoTestBuildOptionsFieldSet(FieldSet):
    required_fields = (
        GoTestRaceDetectorEnabledField,
        GoTestMemorySanitizerEnabledField,
        GoTestAddressSanitizerEnabledField,
    )

    test_race: GoTestRaceDetectorEnabledField
    test_msan: GoTestMemorySanitizerEnabledField
    test_asan: GoTestAddressSanitizerEnabledField


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
    """Returns True if this platform supports interoperation with the C/C++ memory sanitizer."""
    if goroot.goos == "linux":
        return goroot.goarch in ("amd64", "arm64")
    elif goroot.goos == "freebsd":
        return goroot.goarch == "amd64"
    else:
        return False


# Adapted from https://github.com/golang/go/blob/920f87adda5412a41036a862cf2139bed24aa533/src/internal/platform/supported.go#L42-L49
def asan_supported(goroot: GoRoot) -> bool:
    """Returns True if this platform supports interoperation with the C/C++ address sanitizer."""
    if goroot.goos == "linux":
        return goroot.goarch in ("arm64", "amd64", "riscv64", "ppc64le")
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
            f"The Go data race detector would have been enabled for target `{request.address} "
            f"because {race_detector_reason}, "
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
            f"Interoperation with the C/C++ memory sanitizer would have been enabled for target `{request.address}` "
            f"because {msan_reason}, "
            f"but the memory sanitizer is not supported on platform {goroot.goos}/{goroot.goarch}."
        )
        with_msan = False

    # Extract the `with_asan` value for this target.
    with_asan, asan_reason = _first_non_none_value(
        [
            (
                True if go_test_subsystem.force_asan and test_target_fields else None,
                "the `[go-test].force_asan` option is in effect",
            ),
            (
                test_target_fields.test_asan.value,
                f"{GoTestAddressSanitizerEnabledField.alias}={test_target_fields.test_asan.value} on target `{request.address}`",
            )
            if test_target_fields
            else None,
            (
                target_fields.asan.value,
                f"{GoAddressSanitizerEnabledField.alias}={target_fields.asan.value} on target `{request.address}`",
            )
            if target_fields
            else None,
            (
                go_mod_target_fields.asan.value,
                f"{GoAddressSanitizerEnabledField.alias}={go_mod_target_fields.asan.value} on target `{request.address}`",
            )
            if go_mod_target_fields
            else None,
            (False, "default"),
        ]
    )
    if with_asan and not asan_supported(goroot):
        logger.warning(
            f"Interoperation with the C/C++ address sanitizer would have been enabled for target `{request.address}` "
            f"because {asan_reason}, "
            f"but the address sanitizer is not supported on platform {goroot.goos}/{goroot.goarch}."
        )
        with_asan = False

    # Ensure that only one of the race detector, memory sanitizer, and address sanitizer are ever enabled
    # at a single time.
    if with_race_detector and with_msan:
        raise ValueError(
            "The Go data race detector and C/C++ memory sanitizer cannot be enabled at the same time. "
            f"The Go data race detector is enabled because {race_detector_reason}. "
            f"The C/C++ memory sanitizer is enabled because {msan_reason}."
        )
    if with_race_detector and with_asan:
        raise ValueError(
            "The Go data race detector and C/C++ address sanitizer cannot be enabled at the same time. "
            f"The Go data race detector is enabled because {race_detector_reason}. "
            f"The C/C++ address sanitizer is enabled because {asan_reason}."
        )
    if with_msan and with_asan:
        raise ValueError(
            "The C/C++ memory and address sanitizers cannot be enabled at the same time. "
            f"The C/C++ memory sanitizer is enabled because {msan_reason}. "
            f"The C/C++ address sanitizer is enabled because {asan_reason}."
        )

    # Extract any extra compiler flags specified on `go_mod` or `go_binary` targets.
    # Note: A `compiler_flags` field specified on a `go_package` target is extracted elsewhere.
    compiler_flags: list[str] = []
    if go_mod_target_fields is not None:
        # To avoid duplication of options, only add the module-specific compiler flags if the target for this request
        # is not a `go_mod` target (i.e., because it does not conform to the field set or has a different address).
        if target_fields is None or go_mod_target_fields.address != target_fields.address:
            compiler_flags.extend(go_mod_target_fields.compiler_flags.value or [])
    if target_fields is not None:
        compiler_flags.extend(target_fields.compiler_flags.value or [])

    # Extract any extra linker flags specified on `go_mod` or `go_binary` targets.
    # Note: A `compiler_flags` field specified on a `go_package` target is extracted elsewhere.
    linker_flags: list[str] = []
    if go_mod_target_fields is not None:
        # To avoid duplication of options, only add the module-specific compiler flags if the target for this request
        # is not a `go_mod` target (i.e., because it does not conform to the field set or has a different address).
        if target_fields is None or go_mod_target_fields.address != target_fields.address:
            linker_flags.extend(go_mod_target_fields.linker_flags.value or [])
    if target_fields is not None:
        linker_flags.extend(target_fields.linker_flags.value or [])

    # Extract any extra assembler flags specified on `go_mod` or `go_binary` targets.
    # Note: An `assembler_flags` field specified on a `go_package` target is extracted elsewhere.
    assembler_flags: list[str] = []
    if go_mod_target_fields is not None:
        # To avoid duplication of options, only add the module-specific assembler flags if the target for this request
        # is not a `go_mod` target (i.e., because it does not conform to the field set or has a different address).
        if target_fields is None or go_mod_target_fields.address != target_fields.address:
            assembler_flags.extend(go_mod_target_fields.assembler_flags.value or [])
    if target_fields is not None:
        assembler_flags.extend(target_fields.assembler_flags.value or [])

    return GoBuildOptions(
        cgo_enabled=cgo_enabled,
        with_race_detector=with_race_detector,
        with_msan=with_msan,
        with_asan=with_asan,
        compiler_flags=tuple(compiler_flags),
        linker_flags=tuple(linker_flags),
        assembler_flags=tuple(assembler_flags),
    )


def rules():
    return (
        *collect_rules(),
        *go_mod.rules(),
        *goroot.rules(),
        *graph.rules(),
    )
