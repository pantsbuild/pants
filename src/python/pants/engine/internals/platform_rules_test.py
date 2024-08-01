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
    EnvironmentsSubsystem,
    EnvironmentTarget,
    LocalEnvironmentTarget,
    PassThroughEnvVars,
    RemoteEnvironmentTarget,
    RemotePlatformField,
)
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars, EnvironmentVarsRequest
from pants.engine.environment import EnvironmentName
from pants.engine.internals.platform_rules import (
    complete_environment_vars,
    current_platform,
    environment_path_variable,
)
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
        envs_enabled: bool = True,
        env_tgt: LocalEnvironmentTarget | RemoteEnvironmentTarget | DockerEnvironmentTarget | None,
        remote_execution: bool,
        expected: Platform,
    ) -> None:
        global_options = create_subsystem(GlobalOptions, remote_execution=remote_execution)
        name = "name"
        env_subsystem = create_subsystem(
            EnvironmentsSubsystem,
            names={name: "addr"} if envs_enabled else {},
        )
        result = run_rule_with_mocks(
            current_platform,
            rule_args=[EnvironmentTarget(name, env_tgt), global_options, env_subsystem],
        )
        assert result == expected

    assert_platform(env_tgt=None, remote_execution=False, expected=Platform.create_for_localhost())
    assert_platform(
        env_tgt=None, envs_enabled=False, remote_execution=True, expected=Platform.linux_x86_64
    )
    assert_platform(
        env_tgt=None,
        envs_enabled=True,
        remote_execution=True,
        expected=Platform.create_for_localhost(),
    )

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
        envs_enabled: bool = True,
        env_tgt: LocalEnvironmentTarget | RemoteEnvironmentTarget | DockerEnvironmentTarget | None,
        remote_execution: bool,
        expected_env: dict,
    ) -> None:
        global_options = create_subsystem(GlobalOptions, remote_execution=remote_execution)
        name = "name"
        env_subsystem = create_subsystem(
            EnvironmentsSubsystem,
            names={name: "addr"} if envs_enabled else {},
        )

        def mock_env_process(process: Process) -> ProcessResult:
            return Mock(
                stdout=(
                    b"CONTAINER_VAR=container_val\0COMMON_VAR=docker"
                    if "Docker" in process.description
                    else b"REMOTE_VAR=remote_val\0COMMON_VAR=remote"
                )
            )

        local_env = {
            "USER_SHELL_VAR": "user_val",
            "COMMON_VAR": "local",
        }

        result = run_rule_with_mocks(
            complete_environment_vars,
            rule_args=[
                SessionValues({CompleteEnvironmentVars: CompleteEnvironmentVars(local_env)}),
                EnvironmentTarget(name, env_tgt),
                global_options,
                env_subsystem,
            ],
            mock_gets=[
                MockGet(output_type=ProcessResult, input_types=(Process,), mock=mock_env_process)
            ],
        )
        assert dict(result) == expected_env

    assert_env_vars(
        env_tgt=None,
        remote_execution=False,
        expected_env={"USER_SHELL_VAR": "user_val", "COMMON_VAR": "local"},
    )
    assert_env_vars(
        env_tgt=None,
        envs_enabled=False,
        remote_execution=True,
        expected_env={
            "REMOTE_VAR": "remote_val",
            "COMMON_VAR": "remote",
        },
    )
    assert_env_vars(
        env_tgt=None,
        envs_enabled=True,
        remote_execution=True,
        expected_env={
            "USER_SHELL_VAR": "user_val",
            "COMMON_VAR": "local",
        },
    )

    for re in (False, True):
        assert_env_vars(
            env_tgt=LocalEnvironmentTarget({}, Address("dir")),
            remote_execution=re,
            expected_env={
                "USER_SHELL_VAR": "user_val",
                "COMMON_VAR": "local",
            },
        )

    for re in (False, True):
        assert_env_vars(
            env_tgt=DockerEnvironmentTarget(
                {
                    DockerImageField.alias: "my_img",
                    PassThroughEnvVars.alias: ["COMMON_VAR", "USER_SHELL_VAR"],
                },
                Address("dir"),
            ),
            remote_execution=re,
            expected_env={
                "USER_SHELL_VAR": "user_val",
                "CONTAINER_VAR": "container_val",
                "COMMON_VAR": "local",
            },
        )

    for re in (False, True):
        assert_env_vars(
            env_tgt=RemoteEnvironmentTarget(
                {
                    PassThroughEnvVars.alias: ["COMMON_VAR", "USER_SHELL_VAR"],
                },
                Address("dir"),
            ),
            remote_execution=re,
            expected_env={
                "USER_SHELL_VAR": "user_val",
                "REMOTE_VAR": "remote_val",
                "COMMON_VAR": "local",
            },
        )


@pytest.mark.parametrize(
    ("env", "expected_entries"),
    [
        pytest.param(
            {"PATH": "foo/bar:baz:/qux/quux"}, ["foo/bar", "baz", "/qux/quux"], id="populated_PATH"
        ),
        pytest.param({"PATH": ""}, [], id="empty_PATH"),
        pytest.param({}, [], id="unset_PATH"),
    ],
)
def test_get_environment_paths(env: dict[str, str], expected_entries: list[str]) -> None:
    def mock_environment_vars_subset(_req: EnvironmentVarsRequest) -> EnvironmentVars:
        return EnvironmentVars(env)

    paths = run_rule_with_mocks(
        environment_path_variable,
        mock_gets=[
            MockGet(
                output_type=EnvironmentVars,
                input_types=(CompleteEnvironmentVars, EnvironmentVarsRequest),
                mock=mock_environment_vars_subset,
            )
        ],
    )
    assert list(paths) == expected_entries


def test_docker_complete_env_vars() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(CompleteEnvironmentVars, [EnvironmentName])],
        target_types=[DockerEnvironmentTarget],
        inherent_environment=EnvironmentName("docker"),
    )
    localhost_platform = Platform.create_for_localhost()
    if localhost_platform == Platform.linux_arm64:
        image_sha = "65a4aad1156d8a0679537cb78519a17eb7142e05a968b26a5361153006224fdc"
        platform = Platform.linux_arm64.value
    else:
        image_sha = "a1801b843b1bfaf77c501e7a6d3f709401a1e0c83863037fa3aab063a7fdb9dc"
        platform = Platform.linux_x86_64.value

    rule_runner.write_files(
        {
            "BUILD": dedent(
                f"""\
                docker_environment(
                    name='docker',
                    image='centos@sha256:{image_sha}',
                    platform='{platform}',
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
