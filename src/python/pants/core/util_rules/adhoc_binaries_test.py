# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

import pytest

from pants.build_graph.address import Address
from pants.core.target_types import FileTarget
from pants.core.util_rules import adhoc_binaries
from pants.core.util_rules.environments import (
    EnvironmentName,
    EnvironmentTarget,
    LocalEnvironmentTarget,
)
from pants.engine.platform import Platform
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks

SENTINEL = object()


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *adhoc_binaries.rules(),
            QueryRule(
                adhoc_binaries.PythonBuildStandaloneBinary,
                [EnvironmentName, adhoc_binaries._DownloadPythonBuildStandaloneBinaryRequest],
            ),
        ],
        target_types=[LocalEnvironmentTarget, FileTarget],
    )


PLATFORM = Platform.linux_x86_64


@pytest.mark.parametrize("env_tgt", [None, LocalEnvironmentTarget({}, address=Address(""))])
def test_local(env_tgt) -> None:
    result = run_rule_with_mocks(
        adhoc_binaries.get_python_for_scripts,
        rule_args=[EnvironmentTarget(env_tgt)],
        mock_gets=[
            MockGet(
                output_type=adhoc_binaries.PythonBuildStandaloneBinary,
                input_types=(adhoc_binaries._DownloadPythonBuildStandaloneBinaryRequest,),
                mock=lambda _: pytest.fail(),
            )
        ],
    )
    assert result.path == sys.executable


def test_docker_uses_helper() -> None:
    result = run_rule_with_mocks(
        adhoc_binaries.get_python_for_scripts,
        rule_args=[EnvironmentTarget(FileTarget({"source": ""}, address=Address("")))],
        mock_gets=[
            MockGet(
                output_type=adhoc_binaries.PythonBuildStandaloneBinary,
                input_types=(adhoc_binaries._DownloadPythonBuildStandaloneBinaryRequest,),
                mock=lambda _: SENTINEL,
            )
        ],
    )
    assert result is SENTINEL


def test_docker_helper(rule_runner):
    rule_runner.write_files(
        {
            "BUILD": "local_environment(name='local')",
        }
    )
    rule_runner.set_options(["--environments-preview-names={'local': '//:local'}"])
    pbs = rule_runner.request(
        adhoc_binaries.PythonBuildStandaloneBinary,
        [adhoc_binaries._DownloadPythonBuildStandaloneBinaryRequest()],
    )
    assert pbs.path == None
