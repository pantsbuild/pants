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


def pytest_generate_tests(metafunc):
    """Parametrize tests that require specific Go versions."""
    # Check if the test has the require_go_version_max marker.
    marker = metafunc.definition.get_closest_marker("require_go_version_max")
    if not marker:
        return

    # Extract the maximum version from the marker.
    if len(marker.args) < 2:
        pytest.fail(
            f"require_go_version_max marker requires 2 args (major, minor), got {marker.args}"
        )
        return

    max_major, max_minor = marker.args[0], marker.args[1]
    max_version = (max_major, max_minor)

    # Discover available Go binaries
    available_go = _discover_go_binaries()

    # Filter for compatible versions (<= max_version)
    compatible_go = [(path, version) for path, version in available_go if version <= max_version]

    # Parametrize the test if it accepts a `go_binary_path` fixture.
    if "go_binary_path" in metafunc.fixturenames:
        if compatible_go:
            # Use the newest compatible version.
            best_go_path, best_version = compatible_go[0]
            metafunc.parametrize(
                "go_binary_path",
                [best_go_path],
                ids=[f"go{best_version[0]}.{best_version[1]}"],
            )
        else:
            # Parametrize with None and mark to skip, so the test shows as skipped rather than uncollected.
            available_versions = [f"{v[0]}.{v[1]}" for _, v in available_go]
            skip_msg = (
                f"Test requires Go <= {max_major}.{max_minor}, but only found: "
                f"{', '.join(available_versions) if available_versions else 'none'}"
            )
            metafunc.parametrize(
                "go_binary_path",
                [pytest.param(None, marks=pytest.mark.skip(reason=skip_msg))],
                ids=["no-compatible-go"],
            )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "require_go_version_max(major, minor): mark test to require Go version <= specified",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    if not _go_present():
        pytest.skip(reason="`go` not present on PATH")
