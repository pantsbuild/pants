# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import Generator, NoReturn
from unittest.mock import Mock

import pytest

from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.subsystems.nodejs import (
    NodeJS,
    NodejsBinaries,
    _BinaryPathsPerVersion,
    _get_nvm_root,
    _NvmPathsRequest,
    _NvmSearchPaths,
    determine_nodejs_binaries,
)
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget
from pants.backend.python import target_types_rules
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    ExternalToolVersion,
)
from pants.core.util_rules.system_binaries import BinaryNotFoundError, BinaryPath
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.platform import Platform
from pants.engine.process import ProcessResult
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.contextutil import temporary_dir


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *nodejs.rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(ProcessResult, [nodejs.NodeJSToolProcess]),
            QueryRule(NodejsBinaries, ()),
            QueryRule(_NvmSearchPaths, (_NvmPathsRequest,)),
        ],
        target_types=[JSSourcesGeneratorTarget],
    )


def test_npx_process(rule_runner: RuleRunner):
    result = rule_runner.request(
        ProcessResult,
        [
            nodejs.NodeJSToolProcess.npx(
                npm_package="",
                args=("--version",),
                description="Testing NpxProcess",
            )
        ],
    )

    assert result.stdout.strip() == b"8.5.5"


def test_npm_process(rule_runner: RuleRunner):
    result = rule_runner.request(
        ProcessResult,
        [
            nodejs.NodeJSToolProcess.npm(
                args=("--version",),
                description="Testing NpmProcess",
            )
        ],
    )

    assert result.stdout.strip() == b"8.5.5"


def given_known_version(version: str) -> str:
    return f"{version}|linux_x86_64|1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd|333333"


_SEMVER_1_1_0 = given_known_version("1.1.0")
_SEMVER_2_1_0 = given_known_version("2.1.0")
_SEMVER_2_2_0 = given_known_version("2.2.0")
_SEMVER_2_2_2 = given_known_version("2.2.2")
_SEMVER_3_0_0 = given_known_version("3.0.0")


@pytest.mark.parametrize(
    ("semver_range", "expected"),
    [
        pytest.param("1.x", _SEMVER_1_1_0, id="x_range"),
        pytest.param("2.0 - 3.0", _SEMVER_2_1_0, id="hyphen"),
        pytest.param(">2.2.0", _SEMVER_2_2_2, id="gt"),
        pytest.param("2.2.x", _SEMVER_2_2_0, id="x_range_patch"),
        pytest.param("~2.2.0", _SEMVER_2_2_0, id="thilde"),
        pytest.param("^2.2.0", _SEMVER_2_2_0, id="caret"),
        pytest.param("3.0.0", _SEMVER_3_0_0, id="exact"),
        pytest.param("=3.0.0", _SEMVER_3_0_0, id="exact_equals"),
        pytest.param("<3.0.0 >2.1", _SEMVER_2_2_0, id="and_range"),
        pytest.param(">2.1 || <2.1", _SEMVER_1_1_0, id="or_range"),
    ],
)
def test_node_version_from_semver_download(semver_range: str, expected: str) -> None:
    nodejs_subsystem = Mock(spec_set=NodeJS)
    nodejs_subsystem.version = semver_range
    nodejs_subsystem.known_versions = [
        _SEMVER_1_1_0,
        _SEMVER_2_1_0,
        _SEMVER_2_2_0,
        _SEMVER_2_2_2,
        _SEMVER_3_0_0,
    ]
    run_rule_with_mocks(
        determine_nodejs_binaries,
        rule_args=(nodejs_subsystem, Platform.linux_x86_64, _BinaryPathsPerVersion()),
        mock_gets=[
            MockGet(
                DownloadedExternalTool,
                (ExternalToolRequest,),
                mock=lambda *_: DownloadedExternalTool(EMPTY_DIGEST, "myexe"),
            ),
        ],
    )

    nodejs_subsystem.download_known_version.assert_called_once_with(
        ExternalToolVersion.decode(expected), Platform.linux_x86_64
    )


@pytest.mark.parametrize(
    ("semver_range", "expected_path"),
    [
        pytest.param("1.x", "1/1/0", id="x_range"),
        pytest.param("2.0 - 3.0", "2/1/0", id="hyphen"),
        pytest.param(">2.2.0", "2/2/2", id="gt"),
        pytest.param("2.2.x", "2/2/0", id="x_range_patch"),
        pytest.param("~2.2.0", "2/2/0", id="thilde"),
        pytest.param("^2.2.0", "2/2/0", id="caret"),
        pytest.param("3.0.0", "3/0/0", id="exact"),
        pytest.param("=3.0.0", "3/0/0", id="exact_equals"),
        pytest.param("<3.0.0 >2.1", "2/2/0", id="and_range"),
        pytest.param(">2.1 || <2.1", "1/1/0", id="or_range"),
    ],
)
def test_node_version_from_semver_bootstrap(semver_range: str, expected_path: str) -> None:
    nodejs_subsystem = Mock(spec_set=NodeJS)
    nodejs_subsystem.version = semver_range
    discoverable_versions = _BinaryPathsPerVersion(
        {
            "1.1.0": (BinaryPath("1/1/0/node"),),
            "2.1.0": (BinaryPath("2/1/0/node"),),
            "2.2.0": (BinaryPath("2/2/0/node"),),
            "2.2.2": (BinaryPath("2/2/2/node"),),
            "3.0.0": (BinaryPath("3/0/0/node"),),
        }
    )

    def mock_download(*_) -> NoReturn:
        raise AssertionError("Should not run.")

    result = run_rule_with_mocks(
        determine_nodejs_binaries,
        rule_args=(nodejs_subsystem, Platform.linux_x86_64, discoverable_versions),
        mock_gets=[
            MockGet(DownloadedExternalTool, (ExternalToolRequest,), mock=mock_download),
        ],
    )

    assert result.binary_dir == expected_path


def test_finding_no_node_version_is_an_error() -> None:
    nodejs_subsystem = Mock(spec_set=NodeJS)
    nodejs_subsystem.version = "*"
    nodejs_subsystem.known_versions = []
    discoverable_versions = _BinaryPathsPerVersion()

    def mock_download(*_) -> DownloadedExternalTool:
        return DownloadedExternalTool(EMPTY_DIGEST, "myexe")

    with pytest.raises(BinaryNotFoundError):
        run_rule_with_mocks(
            determine_nodejs_binaries,
            rule_args=(nodejs_subsystem, Platform.linux_x86_64, discoverable_versions),
            mock_gets=[
                MockGet(DownloadedExternalTool, (ExternalToolRequest,), mock=mock_download),
            ],
        )


def mock_nodejs(version: str) -> str:
    """Return a bash script that emulates `node --version`."""
    return dedent(
        f"""\
        #!/bin/bash

        if [[ "$1" == '--version' ]]; then
            echo '{version}'
        fi
        """
    )


def test_find_valid_binary(rule_runner: RuleRunner) -> None:
    mock_binary = mock_nodejs("v3.0.0")
    with temporary_dir() as tmpdir:
        binary_dir = Path(tmpdir) / "bin"
        binary_dir.mkdir()
        binary_path = binary_dir / "node"
        binary_path.write_text(mock_binary)
        binary_path.chmod(binary_path.stat().st_mode | stat.S_IEXEC)

        rule_runner.set_options(
            [
                f"--nodejs-search-path=['{binary_dir}']",
                "--nodejs-version=>2",
            ],
            env_inherit={"PATH"},
        )
        result = rule_runner.request(NodejsBinaries, ())
    assert result.binary_dir == str(binary_dir)


@pytest.mark.parametrize(
    "env, expected_directory",
    [
        pytest.param({"NVM_DIR": "/somewhere/.nvm"}, "/somewhere/.nvm", id="explicit_nvm_dir"),
        pytest.param(
            {"HOME": "/somewhere-else", "XDG_CONFIG_HOME": "/somewhere"},
            "/somewhere/.nvm",
            id="xdg_config_home_set",
        ),
        pytest.param({"HOME": "/somewhere-else"}, "/somewhere-else/.nvm", id="home_dir_set"),
        pytest.param({}, None, id="no_dirs_set"),
    ],
)
def test_get_nvm_root(env: dict[str, str], expected_directory: str | None) -> None:
    def mock_environment_vars(_req: EnvironmentVarsRequest) -> EnvironmentVars:
        return EnvironmentVars(env)

    result = run_rule_with_mocks(
        _get_nvm_root,
        mock_gets=[MockGet(EnvironmentVars, (EnvironmentVarsRequest,), mock_environment_vars)],
    )
    assert result == expected_directory


@contextmanager
def fake_nvm_root(
    fake_versions: list[str], fake_local_version: str
) -> Generator[tuple[str, tuple[str, ...], tuple[str]], None, None]:
    with temporary_dir() as nvm_root:
        fake_version_dirs = tuple(
            os.path.join(nvm_root, "versions", "node", v, "bin") for v in fake_versions
        )
        for d in fake_version_dirs:
            os.makedirs(d)
        fake_local_version_dirs = (
            os.path.join(nvm_root, "versions", "node", fake_local_version, "bin"),
        )
        yield nvm_root, fake_version_dirs, fake_local_version_dirs


def test_get_local_nvm_paths(rule_runner: RuleRunner) -> None:
    local_nvm_version = "3.5.5"
    all_nvm_versions = ["2.7.14", local_nvm_version]
    rule_runner.write_files({".nvmrc": f"{local_nvm_version}\n"})
    with fake_nvm_root(all_nvm_versions, local_nvm_version) as (
        nvm_root,
        expected_paths,
        expected_local_paths,
    ):
        rule_runner.set_session_values(
            {CompleteEnvironmentVars: CompleteEnvironmentVars({"NVM_DIR": nvm_root})}
        )
        env_name = "name"
        tgt = EnvironmentTarget(env_name, LocalEnvironmentTarget({}, Address("flem")))
        paths = rule_runner.request(
            _NvmSearchPaths,
            [_NvmPathsRequest(tgt, False)],
        )
        local_paths = rule_runner.request(
            _NvmSearchPaths,
            [_NvmPathsRequest(tgt, True)],
        )
    assert set(expected_paths) == set(paths)
    assert set(expected_local_paths) == set(local_paths)
