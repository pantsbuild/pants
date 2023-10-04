# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

import pytest

from pants.build_graph.address import Address
from pants.core.target_types import FileTarget
from pants.core.util_rules import adhoc_binaries
from pants.core.util_rules.adhoc_binaries import (
    PythonBuildStandaloneBinary,
    _DownloadPythonBuildStandaloneBinaryRequest,
    _PythonBuildStandaloneBinary,
)
from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *adhoc_binaries.rules(),
            QueryRule(
                _PythonBuildStandaloneBinary,
                [_DownloadPythonBuildStandaloneBinaryRequest],
            ),
        ],
        target_types=[LocalEnvironmentTarget, FileTarget],
    )


@pytest.mark.parametrize("env_tgt", [None, LocalEnvironmentTarget({}, address=Address(""))])
def test_local(env_tgt) -> None:
    result = run_rule_with_mocks(
        adhoc_binaries.get_python_for_scripts,
        rule_args=[EnvironmentTarget("local", env_tgt)],
        mock_gets=[
            MockGet(
                output_type=_PythonBuildStandaloneBinary,
                input_types=(_DownloadPythonBuildStandaloneBinaryRequest,),
                mock=lambda _: pytest.fail(),
            )
        ],
    )
    assert result == adhoc_binaries.PythonBuildStandaloneBinary(sys.executable)


def test_docker_uses_helper() -> None:
    result = run_rule_with_mocks(
        adhoc_binaries.get_python_for_scripts,
        rule_args=[EnvironmentTarget("docker", FileTarget({"source": ""}, address=Address("")))],
        mock_gets=[
            MockGet(
                output_type=_PythonBuildStandaloneBinary,
                input_types=(_DownloadPythonBuildStandaloneBinaryRequest,),
                mock=lambda _: _PythonBuildStandaloneBinary(""),
            )
        ],
    )
    assert result == PythonBuildStandaloneBinary("")


def test_docker_helper(rule_runner: RuleRunner):
    rule_runner.write_files(
        {
            "BUILD": "local_environment(name='local')",
        }
    )
    rule_runner.set_options(
        ["--environments-preview-names={'local': '//:local'}"], env_inherit={"PATH"}
    )
    pbs = rule_runner.request(
        _PythonBuildStandaloneBinary,
        [_DownloadPythonBuildStandaloneBinaryRequest()],
    )
    assert not pbs.path.startswith("/")
