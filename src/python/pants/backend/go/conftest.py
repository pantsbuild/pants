# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from functools import lru_cache

import pytest


@lru_cache(None)
def _go_present() -> bool:
    try:
        subprocess.run(
            ["go", "version"], check=False, env={"PATH": os.getenv("PATH") or ""}
        ).returncode
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def _parse_go_version(version_string: str) -> tuple[int, int] | None:
    """Parse 'go1.24.3' output to (1, 24)."""
    if not version_string.startswith("go"):
        return None

    # Strip "go" prefix and split on "."
    version_parts = version_string[2:].split(".")

    if len(version_parts) < 2:
        return None

    try:
        major = int(version_parts[0])
        minor = int(version_parts[1])
        return (major, minor)
    except (ValueError, IndexError):
        return None


@lru_cache(None)
def _discover_go_binaries() -> list[tuple[str, tuple[int, int]]]:
    """Discover all Go binaries in PATH and return sorted by version (newest first)."""
    path_env = os.getenv("PATH", "")
    if not path_env:
        return []

    go_binaries = []
    seen_paths = set()

    for path_dir in path_env.split(os.pathsep):
        if not path_dir or not os.path.isdir(path_dir):
            continue

        go_binary = os.path.join(path_dir, "go")
        if os.path.isfile(go_binary) and os.access(go_binary, os.X_OK):
            # Resolve symlinks to avoid duplicates.
            real_path = os.path.realpath(go_binary)
            if real_path in seen_paths:
                continue
            seen_paths.add(real_path)

            try:
                result = subprocess.run(
                    [go_binary, "env", "GOVERSION"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0:
                    version = _parse_go_version(result.stdout.strip())
                    if version:
                        go_binaries.append((go_binary, version))
            except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
                continue

    # Sort by version (newest first).
    go_binaries.sort(key=lambda x: x[1], reverse=True)
    return go_binaries


# The Go version from which Pants registers coverage counters through
# `testing/internal/testdeps` rather than `testing.RegisterCover`. Keep in sync with
# `pants.backend.go.util_rules.coverage.registers_coverage_via_testdeps`.
_TESTDEPS_COVERAGE_MIN_GO_VERSION = (1, 25)


@lru_cache(None)
def _go_binaries_per_coverage_mechanism() -> list[tuple[str, tuple[int, int]]]:
    """The newest Go binary on `PATH` for each coverage registration mechanism Pants implements.

    CI installs both a Go v1.25+ and a Go v1.24 toolchain precisely so that both mechanisms get
    exercised. Where only one of the two is installed, only that one is returned.
    """
    selected = []
    for uses_testdeps in (True, False):
        for path, version in _discover_go_binaries():  # Newest first.
            if (version >= _TESTDEPS_COVERAGE_MIN_GO_VERSION) is uses_testdeps:
                selected.append((path, version))
                break
    return selected


def pytest_generate_tests(metafunc):
    """Run tests which pin a Go toolchain once per Go coverage registration mechanism."""
    if "go_binary_path" not in metafunc.fixturenames:
        return

    go_binaries = _go_binaries_per_coverage_mechanism()
    if not go_binaries:
        # Parametrize with None and mark to skip, so the test shows as skipped rather than
        # uncollected. `pytest_runtest_setup` would skip it in any case.
        metafunc.parametrize(
            "go_binary_path",
            [pytest.param(None, marks=pytest.mark.skip(reason="`go` not present on PATH"))],
            ids=["no-go"],
        )
        return

    metafunc.parametrize(
        "go_binary_path",
        [path for path, _ in go_binaries],
        ids=[f"go{major}.{minor}" for _, (major, minor) in go_binaries],
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    if not _go_present():
        pytest.skip(reason="`go` not present on PATH")
