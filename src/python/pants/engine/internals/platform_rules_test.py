# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from unittest.mock import Mock

import pytest

from pants.build_graph.address import Address
from pants.core.util_rules.environments import (
    DockerEnvironmentTarget,
    DockerImageField,
    DockerPlatformField,
    EnvironmentTarget,
    LocalEnvironmentTarget,
    RemoteEnvironmentTarget,
    RemotePlatformField,
)
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.environment import EnvironmentName
from pants.engine.internals.platform_rules import complete_environment_vars, current_platform
from pants.engine.internals.session import SessionValues
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.option.global_options import GlobalOptions
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks


@pytest.mark.platform_specific_behavior
def test_current_platform() -> None:
    def assert_platform(
        *,
        env_tgt: LocalEnvironmentTarget | RemoteEnvironmentTarget | DockerEnvironmentTarget | None,
        remote_execution: bool,
        expected: Platform,
    ) -> None:
        global_options = create_subsystem(GlobalOptions, remote_execution=remote_execution)
        result = run_rule_with_mocks(
            current_platform, rule_args=[EnvironmentTarget(env_tgt), global_options]
        )
        assert result == expected

    assert_platform(env_tgt=None, remote_execution=False, expected=Platform.create_for_localhost())
    assert_platform(env_tgt=None, remote_execution=True, expected=Platform.linux_x86_64)

    for re in (False, True):
        assert_platform(
            env_tgt=LocalEnvironmentTarget({}, Address("dir")),
            remote_execution=re,
            expected=Platform.create_for_localhost(),
        )

    for re in (False, True):
        assert_platform(
            env_tgt=DockerEnvironmentTarget(
                {
                    DockerImageField.alias: "my_img",
                    DockerPlatformField.alias: Platform.linux_arm64.value,
                },
                Address("dir"),
            ),
            remote_execution=re,
            expected=Platform.linux_arm64,
        )

    for re in (False, True):
        assert_platform(
            env_tgt=RemoteEnvironmentTarget(
                {RemotePlatformField.alias: Platform.linux_arm64.value}, Address("dir")
            ),
            remote_execution=re,
            expected=Platform.linux_arm64,
        )


@pytest.mark.platform_specific_behavior
def test_complete_env_vars() -> None:
    def assert_env_vars(
        *,
        env_tgt: LocalEnvironmentTarget | RemoteEnvironmentTarget | DockerEnvironmentTarget | None,
        remote_execution: bool,
        expected_env: str,
    ) -> None:
        global_options = create_subsystem(GlobalOptions, remote_execution=remote_execution)

        def mock_env_process(process: Process) -> ProcessResult:
            return Mock(
                stdout=b"DOCKER=true" if "Docker" in process.description else b"REMOTE=true"
            )

        result = run_rule_with_mocks(
            complete_environment_vars,
            rule_args=[
                SessionValues(
                    {CompleteEnvironmentVars: CompleteEnvironmentVars({"LOCAL": "true"})}
                ),
                EnvironmentTarget(env_tgt),
                global_options,
            ],
            mock_gets=[
                MockGet(output_type=ProcessResult, input_types=(Process,), mock=mock_env_process)
            ],
        )
        assert dict(result) == {expected_env: "true"}

    assert_env_vars(env_tgt=None, remote_execution=False, expected_env="LOCAL")
    assert_env_vars(env_tgt=None, remote_execution=True, expected_env="REMOTE")

    for re in (False, True):
        assert_env_vars(
            env_tgt=LocalEnvironmentTarget({}, Address("dir")),
            remote_execution=re,
            expected_env="LOCAL",
        )

    for re in (False, True):
        assert_env_vars(
            env_tgt=DockerEnvironmentTarget({DockerImageField.alias: "my_img"}, Address("dir")),
            remote_execution=re,
            expected_env="DOCKER",
        )

    for re in (False, True):
        assert_env_vars(
            env_tgt=RemoteEnvironmentTarget({}, Address("dir")),
            remote_execution=re,
            expected_env="REMOTE",
        )


def test_docker_complete_env_vars() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(CompleteEnvironmentVars, [])],
        target_types=[DockerEnvironmentTarget],
        singleton_environment=EnvironmentName("docker"),
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                docker_environment(
                    name='docker',
                    image='centos@sha256:a1801b843b1bfaf77c501e7a6d3f709401a1e0c83863037fa3aab063a7fdb9dc',
                    platform='linux_x86_64',
                )
                """
            )
        }
    )
    rule_runner.set_options(["--environments-preview-names={'docker': '//:docker'}"])
    result = dict(rule_runner.request(CompleteEnvironmentVars, []))

    # HOSTNAME is not deterministic across machines, so we don't care about the value.
    assert "HOSTNAME" in result
    result.pop("HOSTNAME")
    assert dict(result) == {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/root",
    }
