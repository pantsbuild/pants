# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from unittest.mock import Mock

import pytest

from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.subsystems.nodejs import (
    NodeJS,
    NodeJsBootstrap,
    determine_nodejs_binaries,
)
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget
from pants.backend.python import target_types_rules
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    ExternalToolVersion,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.platform import Platform
from pants.engine.process import ProcessResult
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *nodejs.rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(ProcessResult, [nodejs.NodeJSToolProcess]),
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
def test_node_version_from_semver(semver_range: str, expected: str):
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
        rule_args=(nodejs_subsystem, NodeJsBootstrap(()), Platform.linux_x86_64),
        mock_gets=[
            MockGet(
                DownloadedExternalTool,
                (ExternalToolRequest,),
                mock=lambda *_: DownloadedExternalTool(EMPTY_DIGEST, "myexe"),
            )
        ],
    )

    nodejs_subsystem.download_known_version.assert_called_once_with(
        ExternalToolVersion.decode(expected), Platform.linux_x86_64
    )
