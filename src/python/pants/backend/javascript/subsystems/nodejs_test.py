# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import stat
from asyncio import Future
from pathlib import Path
from textwrap import dedent
from typing import NoReturn
from unittest.mock import MagicMock, Mock

import pytest

from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.subsystems.nodejs import (
    CorepackToolDigest,
    CorepackToolRequest,
    NodeJS,
    NodeJSBinaries,
    NodeJSProcessEnvironment,
    _BinaryPathsPerVersion,
    _get_nvm_root,
    determine_nodejs_binaries,
    node_process_environment,
)
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget
from pants.backend.python import target_types_rules
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    ExternalToolVersion,
)
from pants.core.util_rules.search_paths import (
    VersionManagerSearchPaths,
    VersionManagerSearchPathsRequest,
)
from pants.core.util_rules.system_binaries import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryShims,
    BinaryShimsRequest,
)
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import CreateDigest, Digest, MergeDigests, Snapshot
from pants.engine.internals.native_engine import EMPTY_DIGEST, EMPTY_FILE_DIGEST
from pants.engine.platform import Platform
from pants.engine.process import (
    Process,
    ProcessExecutionEnvironment,
    ProcessResult,
    ProcessResultMetadata,
)
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.contextutil import temporary_dir


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *nodejs.rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(ProcessResult, [nodejs.NodeJSToolProcess]),
            QueryRule(NodeJSBinaries, ()),
            QueryRule(VersionManagerSearchPaths, (VersionManagerSearchPathsRequest,)),
            QueryRule(CorepackToolDigest, (CorepackToolRequest,)),
        ],
        target_types=[JSSourcesGeneratorTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def get_snapshot(rule_runner: RuleRunner, digest: Digest) -> Snapshot:
    return rule_runner.request(Snapshot, [digest])


@pytest.mark.parametrize("package_manager", ["npm", "pnpm", "yarn"])
def test_corepack_without_explicit_version_contains_installation(
    rule_runner: RuleRunner, package_manager: str
):
    result = rule_runner.request(
        CorepackToolDigest, [CorepackToolRequest(package_manager, version=None)]
    )

    snapshot = get_snapshot(rule_runner, result.digest)

    assert f"._corepack_home/v1/{package_manager}" in snapshot.dirs


@pytest.mark.parametrize("package_manager", ["npm@7.0.0", "pnpm@2.0.0", "yarn@1.0.0"])
def test_corepack_with_explicit_version_contains_requested_installation(
    rule_runner: RuleRunner, package_manager: str
):
    binary, version = package_manager.split("@")

    result = rule_runner.request(CorepackToolDigest, [CorepackToolRequest(binary, version)])
    snapshot = get_snapshot(rule_runner, result.digest)

    assert f"._corepack_home/v1/{binary}/{version}" in snapshot.dirs


def test_npm_process(rule_runner: RuleRunner):
    rule_runner.set_options(["--nodejs-package-managers={'npm': '8.5.5'}"], env_inherit={"PATH"})
    result = rule_runner.request(
        ProcessResult,
        [nodejs.NodeJSToolProcess.npm(args=("--version",), description="Testing NpmProcess")],
    )

    assert result.stdout.strip() == b"8.5.5"


def test_npm_process_with_different_version(rule_runner: RuleRunner):
    rule_runner.set_options(["--nodejs-package-managers={'npm': '7.20.0'}"], env_inherit={"PATH"})
    result = rule_runner.request(
        ProcessResult,
        [nodejs.NodeJSToolProcess.npm(args=("--version",), description="Testing NpmProcess")],
    )

    assert result.stdout.strip() == b"7.20.0"


def test_pnpm_process(rule_runner: RuleRunner):
    result = rule_runner.request(
        ProcessResult,
        [
            nodejs.NodeJSToolProcess(
                tool="pnpm",
                tool_version="7.5.0",
                args=("--version",),
                description="Testing pnpm process",
            )
        ],
    )

    assert result.stdout.strip() == b"7.5.0"


def test_yarn_process(rule_runner: RuleRunner):
    result = rule_runner.request(
        ProcessResult,
        [
            nodejs.NodeJSToolProcess(
                tool="yarn",
                tool_version="1.22.19",
                args=("--version",),
                description="Testing yarn process",
            )
        ],
    )

    assert result.stdout.strip() == b"1.22.19"


def given_known_version(version: str) -> str:
    return f"{version}|linux_x86_64|1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd|333333"


@pytest.fixture
def mock_nodejs_subsystem() -> Mock:
    nodejs_subsystem = Mock(spec=NodeJS)
    future: Future[DownloadedExternalTool] = Future()
    future.set_result(DownloadedExternalTool(EMPTY_DIGEST, ""))
    nodejs_subsystem.download_known_version = MagicMock(return_value=future)
    return nodejs_subsystem


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
def test_node_version_from_semver_download(
    mock_nodejs_subsystem: Mock, semver_range: str, expected: str
) -> None:
    nodejs_subsystem = mock_nodejs_subsystem
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
def test_node_version_from_semver_bootstrap(
    mock_nodejs_subsystem: Mock, semver_range: str, expected_path: str
) -> None:
    nodejs_subsystem = mock_nodejs_subsystem
    nodejs_subsystem.version = semver_range
    nodejs_subsystem.known_versions = []
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


def test_finding_no_node_version_is_an_error(mock_nodejs_subsystem: Mock) -> None:
    nodejs_subsystem = mock_nodejs_subsystem
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
                "--nodejs-known-versions=[]",
                "--nodejs-version=>2",
            ],
            env_inherit={"PATH"},
        )
        result = rule_runner.request(NodeJSBinaries, ())
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


@pytest.mark.parametrize(
    "extra_environment, expected",
    [
        pytest.param(
            None,
            {
                "COREPACK_HOME": "{chroot}/._corepack_home",
                "PATH": "{chroot}/shim_cache:._corepack:__node/v18",
                "npm_config_cache": "npm_cache",
            },
            id="no_extra_environment",
        ),
        pytest.param(
            {},
            {
                "COREPACK_HOME": "{chroot}/._corepack_home",
                "PATH": "{chroot}/shim_cache:._corepack:__node/v18",
                "npm_config_cache": "npm_cache",
            },
            id="empty_extra_environment",
        ),
        pytest.param(
            {"PATH": "/usr/bin/"},
            {
                "COREPACK_HOME": "{chroot}/._corepack_home",
                "PATH": "{chroot}/shim_cache:._corepack:__node/v18:/usr/bin/",
                "npm_config_cache": "npm_cache",
            },
            id="extra_environment_extends_path",
        ),
        pytest.param(
            {"PATH": "/usr/bin/", "SOME_VAR": "VAR"},
            {
                "COREPACK_HOME": "{chroot}/._corepack_home",
                "PATH": "{chroot}/shim_cache:._corepack:__node/v18:/usr/bin/",
                "npm_config_cache": "npm_cache",
                "SOME_VAR": "VAR",
            },
            id="extra_environment_adds_to_environment",
        ),
        pytest.param(
            {"npm_config_cache": "I am ignored"},
            {
                "COREPACK_HOME": "{chroot}/._corepack_home",
                "PATH": "{chroot}/shim_cache:._corepack:__node/v18",
                "npm_config_cache": "npm_cache",
            },
            id="extra_environment_cannot_override_some_vars",
        ),
    ],
)
def test_node_process_environment_variables_are_merged(
    extra_environment: dict[str, str] | None, expected: dict[str, str]
) -> None:
    environment = NodeJSProcessEnvironment(
        NodeJSBinaries("__node/v18"),
        "npm_cache",
        BinaryShims(EMPTY_DIGEST, "shim_cache"),
        "._corepack_home",
        "._corepack",
        EnvironmentVars(),
    )

    assert environment.to_env_dict(extra_environment) == expected


def test_node_process_environment_with_tools(rule_runner: RuleRunner) -> None:
    def mock_get_binary_path(request: BinaryPathRequest) -> BinaryPaths:
        # These are the tools that are required by default for any nodejs process to work.
        default_required_tools = [
            "sh",
            "bash",
            "mkdir",
            "rm",
            "touch",
            "which",
            "sed",
            "dirname",
            "uname",
        ]
        if request.binary_name in default_required_tools:
            return BinaryPaths(
                request.binary_name, paths=[BinaryPath(f"/bin/{request.binary_name}")]
            )

        if request.binary_name == "real-tool":
            return BinaryPaths("real-tool", paths=[BinaryPath("/bin/a-real-tool")])

        return BinaryPaths(request.binary_name, ())

    def mock_get_binary_shims(request: BinaryShimsRequest) -> BinaryShims:
        return BinaryShims(EMPTY_DIGEST, "cache_name")

    def mock_environment_vars(request: EnvironmentVarsRequest) -> EnvironmentVars:
        return EnvironmentVars({})

    def mock_create_digest(request: CreateDigest) -> Digest:
        return EMPTY_DIGEST

    def mock_merge_digests(request: MergeDigests) -> Digest:
        return EMPTY_DIGEST

    def mock_enable_corepack_process_result(request: Process) -> ProcessResult:
        return ProcessResult(
            stdout=b"",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr=b"",
            stderr_digest=EMPTY_FILE_DIGEST,
            output_digest=EMPTY_DIGEST,
            metadata=ProcessResultMetadata(
                0,
                ProcessExecutionEnvironment(
                    environment_name=None,
                    platform=Platform.create_for_localhost().value,
                    docker_image=None,
                    remote_execution=False,
                    remote_execution_extra_platform_properties=[],
                    execute_in_workspace=False,
                    keep_sandboxes="never",
                ),
                "ran_locally",
                0,
            ),
        )

    def run(tools: list[str], optional_tools: list[str]) -> None:
        nodejs_binaries = NodeJSBinaries("__node/v18")
        nodejs_options = create_subsystem(
            NodeJS,
            tools=tools,
            optional_tools=optional_tools,
        )
        nodejs_options_env_aware = MagicMock(spec=NodeJS.EnvironmentAware)

        run_rule_with_mocks(
            node_process_environment,
            rule_args=[nodejs_binaries, nodejs_options, nodejs_options_env_aware],
            mock_calls={
                "pants.core.util_rules.system_binaries.create_binary_shims": mock_get_binary_shims,
                "pants.core.util_rules.system_binaries.find_binary": mock_get_binary_path,
                "pants.engine.intrinsics.create_digest": mock_create_digest,
                "pants.engine.intrinsics.merge_digests": mock_merge_digests,
                "pants.engine.internals.platform_rules.environment_vars_subset": mock_environment_vars,
                "pants.engine.process.fallible_to_exec_result_or_raise": mock_enable_corepack_process_result,
            },
        )

    run(tools=["real-tool"], optional_tools=[])

    with pytest.raises(BinaryNotFoundError, match="Cannot find `nonexistent-tool`"):
        run(tools=["real-tool", "nonexistent-tool"], optional_tools=[])

    # Optional non-existent tool should still succeed.
    run(tools=[], optional_tools=["real-tool", "nonexistent-tool"])
