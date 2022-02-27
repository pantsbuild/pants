# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.go.subsystems.golang import GoRoot
from pants.backend.go.subsystems.golang import rules as golang_rules
from pants.core.util_rules.system_binaries import BinaryNotFoundError
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import temporary_dir

EXPECTED_VERSION = "1.17"


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=[*golang_rules(), QueryRule(GoRoot, [])])


def get_goroot(rule_runner: RuleRunner, binary_names_to_scripts: list[tuple[str, str]]) -> GoRoot:
    with temporary_dir() as tmpdir:
        binary_dirs = []
        for i, (name, script) in enumerate(binary_names_to_scripts):
            binary_dir = Path(tmpdir, f"bin{i}")
            binary_dir.mkdir()
            binary_dirs.append(str(binary_dir))

            binary_path = binary_dir / name
            binary_path.write_text(script)
            binary_path.chmod(0o777)

        rule_runner.set_options(
            [
                f"--golang-go-search-paths={repr(binary_dirs)}",
                f"--golang-expected-version={EXPECTED_VERSION}",
            ],
            env_inherit={"PATH"},
        )
        return rule_runner.request(GoRoot, [])


def mock_go_binary(*, version_output: str, env_output: str) -> str:
    """Return a bash script that emulates `go version` and `go env`."""
    return dedent(
        f"""\
        #!/bin/bash

        if [[ "$1" == version ]]; then
            echo '{version_output}'
        else
            echo '{env_output}'
        fi
        """
    )


def test_find_valid_binary(rule_runner: RuleRunner) -> None:
    valid_without_patch = mock_go_binary(
        version_output=f"go version go{EXPECTED_VERSION} darwin/arm64",
        env_output="/valid/binary",
    )
    assert get_goroot(rule_runner, [("go", valid_without_patch)]).path == "/valid/binary"

    valid_with_patch = mock_go_binary(
        version_output=f"go version go{EXPECTED_VERSION}.1 darwin/arm64",
        env_output="/valid/patch_binary",
    )
    assert get_goroot(rule_runner, [("go", valid_with_patch)]).path == "/valid/patch_binary"

    # Should still work even if there are other Go versions with an invalid version.
    invalid_version = mock_go_binary(
        version_output="go version go1.8 darwin/arm64", env_output="/not/valid"
    )
    assert (
        get_goroot(rule_runner, [("go", valid_without_patch), ("go", invalid_version)]).path
        == "/valid/binary"
    )

    # Order of entries matters.
    assert (
        get_goroot(rule_runner, [("go", valid_without_patch), ("go", valid_with_patch)]).path
        == "/valid/binary"
    )
    assert (
        get_goroot(rule_runner, [("go", valid_with_patch), ("go", valid_without_patch)]).path
        == "/valid/patch_binary"
    )


def test_no_binaries(rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError) as e:
        get_goroot(rule_runner, [("not-go", "")])
    exc = e.value.wrapped_exceptions[0]
    assert isinstance(exc, BinaryNotFoundError)
    assert "Cannot find any `go` binaries" in str(exc)


def test_no_valid_versions(rule_runner: RuleRunner) -> None:
    invalid1 = mock_go_binary(
        version_output="go version go1.8 darwin/arm64", env_output="/not/valid1"
    )
    invalid2 = mock_go_binary(
        version_output="go version go1.8 darwin/arm64", env_output="/not/valid2"
    )
    with pytest.raises(ExecutionError) as e:
        get_goroot(rule_runner, [("go", invalid1), ("go", invalid2)])
    exc = e.value.wrapped_exceptions[0]
    assert isinstance(exc, BinaryNotFoundError)
    assert "Cannot find a `go` binary with the expected version" in str(exc)


def test_valid_go_version() -> None:
    go_root = GoRoot("", "1.15")
    for v in range(16):
        assert go_root.is_compatible_version(f"1.{v}") is True
    for v in range(17, 40):
        assert go_root.is_compatible_version(f"1.{v}") is False
    for v in range(2, 4):
        assert go_root.is_compatible_version(f"{v}.0") is False
