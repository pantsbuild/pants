# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.util_rules import stdlib_archives
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.coverage import GoCoverageConfig, GoCoverMode
from pants.backend.go.util_rules.stdlib_archives import (
    PKGDIR_PREFIX,
    GoStdlibArchives,
    GoStdlibArchivesRequest,
    stdlib_archives_compatible,
)
from pants.engine.fs import Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *stdlib_archives.rules(),
            QueryRule(GoStdlibArchives, (GoStdlibArchivesRequest,)),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_harvest_stdlib_archives_without_cgo(rule_runner: RuleRunner) -> None:
    archives = rule_runner.request(GoStdlibArchives, [GoStdlibArchivesRequest(cgo_enabled=False)])
    mapping = archives.import_paths_to_pkg_a_files

    # The Go standard library has ~350 packages with compiled archives (353 on Go 1.26
    # without cgo). Use a loose lower bound so the test does not need updating for every
    # toolchain release.
    assert len(mapping) > 300

    assert mapping["fmt"] == f"{PKGDIR_PREFIX}/fmt.a"
    # Packages with assembly sources are archived like any other package.
    assert mapping["runtime"] == f"{PKGDIR_PREFIX}/runtime.a"
    assert mapping["internal/cpu"] == f"{PKGDIR_PREFIX}/internal/cpu.a"
    # cgo-sensitive packages still have (pure-Go) archives in the non-cgo configuration.
    assert mapping["net"] == f"{PKGDIR_PREFIX}/net.a"
    assert mapping["os/user"] == f"{PKGDIR_PREFIX}/os/user.a"
    # The GOROOT-vendored subtree is archived under its visible import path.
    assert any(ip.startswith("vendor/golang.org/x/") for ip in mapping)
    # `unsafe` has no compiled form and must not appear: consumers must treat a missing key
    # as "fall back to compiling from source".
    assert "unsafe" not in mapping

    # Archive paths mirror import paths under the pkgdir prefix.
    for import_path, archive_path in mapping.items():
        assert archive_path == f"{PKGDIR_PREFIX}/{import_path}.a"

    # The digest contains exactly the mapped archives.
    snapshot = rule_runner.request(Snapshot, [archives.digest])
    assert set(snapshot.files) == set(mapping.values())


def test_harvest_stdlib_archives_with_cgo(rule_runner: RuleRunner) -> None:
    # Note: like the existing cgo tests, this requires a host C toolchain on PATH.
    archives = rule_runner.request(GoStdlibArchives, [GoStdlibArchivesRequest(cgo_enabled=True)])
    mapping = archives.import_paths_to_pkg_a_files

    assert len(mapping) > 300
    assert mapping["fmt"] == f"{PKGDIR_PREFIX}/fmt.a"
    assert mapping["net"] == f"{PKGDIR_PREFIX}/net.a"
    assert mapping["os/user"] == f"{PKGDIR_PREFIX}/os/user.a"
    # `runtime/cgo` only exists in the cgo configuration.
    assert mapping["runtime/cgo"] == f"{PKGDIR_PREFIX}/runtime/cgo.a"


def _golang(use_prebuilt: bool = True) -> GolangSubsystem:
    return create_subsystem(GolangSubsystem, use_prebuilt_stdlib_archives=use_prebuilt)


def test_stdlib_archives_compatible_default_opts() -> None:
    assert stdlib_archives_compatible(GoBuildOptions(), _golang())


def test_stdlib_archives_compatible_escape_hatch() -> None:
    assert not stdlib_archives_compatible(GoBuildOptions(), _golang(use_prebuilt=False))


@pytest.mark.parametrize(
    "build_opts",
    [
        GoBuildOptions(coverage_config=GoCoverageConfig(cover_mode=GoCoverMode.SET)),
        GoBuildOptions(with_race_detector=True),
        GoBuildOptions(with_msan=True),
        GoBuildOptions(with_asan=True),
        GoBuildOptions(compiler_flags=("-N",)),
        GoBuildOptions(assembler_flags=("-S",)),
    ],
)
def test_stdlib_archives_incompatible_with_content_changing_opts(
    build_opts: GoBuildOptions,
) -> None:
    """Any option that changes the content of a stdlib archive must force from-source
    fallback."""
    assert not stdlib_archives_compatible(build_opts, _golang())


@pytest.mark.parametrize("cgo_enabled", [False, True])
def test_stdlib_archives_compatible_with_either_cgo_setting(cgo_enabled: bool) -> None:
    """`cgo_enabled` is a harvest cache-key dimension, not a compatibility gate."""
    assert stdlib_archives_compatible(GoBuildOptions(cgo_enabled=cgo_enabled), _golang())


def test_stdlib_archives_compatible_with_linker_flags() -> None:
    """Linker flags apply at the final link step only; they never affect the content of a
    package archive, so they must not force the stdlib to be rebuilt from source."""
    assert stdlib_archives_compatible(GoBuildOptions(linker_flags=("-s", "-w")), _golang())
