# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Sequence

import pytest

from pants.build_graph.address import Address, ResolveError
from pants.core.util_rules import environments
from pants.core.util_rules.environments import (
    AllEnvironmentTargets,
    AmbiguousEnvironmentError,
    ChosenLocalEnvironmentName,
    CompatiblePlatformsField,
    DockerEnvironmentTarget,
    DockerImageField,
    DockerPlatformField,
    EnvironmentField,
    EnvironmentName,
    EnvironmentNameRequest,
    EnvironmentsSubsystem,
    EnvironmentTarget,
    FallbackEnvironmentField,
    LocalEnvironmentTarget,
    LocalWorkspaceEnvironmentTarget,
    NoFallbackEnvironmentError,
    RemoteEnvironmentCacheBinaryDiscovery,
    RemoteEnvironmentTarget,
    RemoteExtraPlatformPropertiesField,
    SingleEnvironmentNameRequest,
    UnrecognizedEnvironmentError,
    extract_process_config_from_environment,
    resolve_environment_name,
)
from pants.engine.environment import LOCAL_ENVIRONMENT_MATCHER, ChosenLocalWorkspaceEnvironmentName
from pants.engine.internals.docker import DockerResolveImageRequest, DockerResolveImageResult
from pants.engine.platform import Platform
from pants.engine.process import ProcessCacheScope
from pants.engine.target import FieldSet, OptionalSingleSourceField, Target
from pants.option.global_options import GlobalOptions
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import (
    MockGet,
    QueryRule,
    RuleRunner,
    engine_error,
    run_rule_with_mocks,
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *environments.rules(),
            QueryRule(AllEnvironmentTargets, []),
            QueryRule(EnvironmentTarget, [EnvironmentName]),
            QueryRule(EnvironmentName, [EnvironmentNameRequest]),
            QueryRule(EnvironmentName, [SingleEnvironmentNameRequest]),
            QueryRule(ChosenLocalEnvironmentName, []),
            QueryRule(ChosenLocalWorkspaceEnvironmentName, []),
        ],
        target_types=[
            LocalEnvironmentTarget,
            LocalWorkspaceEnvironmentTarget,
            DockerEnvironmentTarget,
            RemoteEnvironmentTarget,
        ],
        inherent_environment=None,
    )


def test_extract_process_config_from_environment() -> None:
    def assert_config(
        *,
        envs_enabled: bool = True,
        env_tgt: LocalEnvironmentTarget
        | LocalWorkspaceEnvironmentTarget
        | RemoteEnvironmentTarget
        | DockerEnvironmentTarget
        | None,
        enable_remote_execution: bool,
        expected_remote_execution: bool,
        expected_docker_image: str | None,
        expected_remote_execution_extra_platform_properties: list[tuple[str, str]] | None = None,
    ) -> None:
        global_options = create_subsystem(
            GlobalOptions,
            remote_execution=enable_remote_execution,
            remote_execution_extra_platform_properties=["global_k=v"],
        )
        name = "name"
        env_subsystem = create_subsystem(
            EnvironmentsSubsystem,
            names={name: "addr"} if envs_enabled else {},
        )
        result = run_rule_with_mocks(
            extract_process_config_from_environment,
            rule_args=[
                EnvironmentTarget(name, env_tgt),
                Platform.linux_arm64,
                global_options,
                env_subsystem,
            ],
            mock_gets=[
                MockGet(
                    output_type=DockerResolveImageResult,
                    input_types=(DockerResolveImageRequest,),
                    mock=lambda req: DockerResolveImageResult("sha256:abc123"),
                )
            ],
        )
        assert result.platform == Platform.linux_arm64.value
        assert result.remote_execution is expected_remote_execution
        if expected_docker_image is not None:
            # TODO(17104): Account for any prepended image name here once implemented.
            assert result.docker_image == "sha256:abc123"
        else:
            assert result.docker_image is None
        assert result.remote_execution_extra_platform_properties == (
            expected_remote_execution_extra_platform_properties or []
        )

    assert_config(
        env_tgt=None,
        enable_remote_execution=False,
        expected_remote_execution=False,
        expected_docker_image=None,
    )
    assert_config(
        env_tgt=None,
        envs_enabled=False,
        enable_remote_execution=True,
        expected_remote_execution=True,
        expected_docker_image=None,
        expected_remote_execution_extra_platform_properties=[("global_k", "v")],
    )
    assert_config(
        env_tgt=None,
        envs_enabled=True,
        enable_remote_execution=True,
        expected_remote_execution=False,
        expected_docker_image=None,
    )

    for re in (False, True):
        assert_config(
            env_tgt=LocalEnvironmentTarget({}, Address("dir")),
            enable_remote_execution=re,
            expected_remote_execution=False,
            expected_docker_image=None,
        )

    for re in (False, True):
        assert_config(
            env_tgt=DockerEnvironmentTarget(
                {
                    DockerImageField.alias: "my_img",
                },
                Address("dir"),
            ),
            enable_remote_execution=re,
            expected_remote_execution=False,
            expected_docker_image="my_img",
        )

    for re in (False, True):
        assert_config(
            env_tgt=RemoteEnvironmentTarget({}, Address("dir")),
            enable_remote_execution=re,
            expected_remote_execution=True,
            expected_docker_image=None,
            # The global option is ignored.
            expected_remote_execution_extra_platform_properties=[],
        )
    assert_config(
        env_tgt=RemoteEnvironmentTarget(
            {RemoteExtraPlatformPropertiesField.alias: ["field_k=v"]}, Address("dir")
        ),
        enable_remote_execution=re,
        expected_remote_execution=True,
        expected_docker_image=None,
        expected_remote_execution_extra_platform_properties=[("field_k", "v")],
    )


def test_all_environments(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                local_environment(name='e1')
                local_environment(name='e2')
                local_environment(name='no-name')
                docker_environment(name='docker', image="centos6:latest")
                """
            )
        }
    )
    rule_runner.set_options(
        ["--environments-preview-names={'e1': '//:e1', 'e2': '//:e2', 'docker': '//:docker'}"]
    )
    result = rule_runner.request(AllEnvironmentTargets, [])
    assert {i: j.address for (i, j) in result.items()} == {
        "e1": Address("", target_name="e1"),
        "e2": Address("", target_name="e2"),
        "docker": Address("", target_name="docker"),
    }


def test_choose_local_environment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                local_environment(name='e1')
                local_environment(name='e2')
                local_environment(name='not-compatible', compatible_platforms=[])
                docker_environment(name='docker', docker_image="centos6:latest")
                """
            )
        }
    )

    def get_env() -> EnvironmentTarget:
        name = rule_runner.request(ChosenLocalEnvironmentName, [])
        return rule_runner.request(EnvironmentTarget, [name.val])

    # If `--names` is not set, do not choose an environment.
    assert get_env().val is None

    rule_runner.set_options(["--environments-preview-names={'e': '//:e1'}"])
    assert get_env().val.address == Address("", target_name="e1")  # type: ignore[union-attr]

    # If `--names` is set, but no compatible platforms, do not choose an environment.
    rule_runner.set_options(["--environments-preview-names={'e': '//:not-compatible'}"])
    assert get_env().val is None

    # Error if >1 compatible targets.
    rule_runner.set_options(["--environments-preview-names={'e1': '//:e1', 'e2': '//:e2'}"])
    with engine_error(AmbiguousEnvironmentError):
        get_env()


def test_resolve_environment_name(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                local_environment(name='local')
                local_environment(
                    name='local-fallback', compatible_platforms=[], fallback_environment='local'
                )
                docker_environment(name='docker', image="centos6:latest")
                remote_environment(name='remote-no-fallback')
                remote_environment(name='remote-fallback', fallback_environment="docker")
                remote_environment(name='remote-bad-fallback', fallback_environment="fake")
                """
            )
        }
    )

    def get_name(v: str) -> EnvironmentName:
        return rule_runner.request(
            EnvironmentName, [EnvironmentNameRequest(v, description_of_origin="foo")]
        )

    # If `--names` is not set, and the local matcher is used, do not choose an environment.
    assert get_name(LOCAL_ENVIRONMENT_MATCHER).val is None
    # Else, error for unrecognized names.
    with engine_error(UnrecognizedEnvironmentError):
        get_name("local")

    env_names_arg = (
        "--environments-preview-names={"
        + "'local': '//:local', "
        + "'local-fallback': '//:local-fallback', "
        + "'docker': '//:docker', "
        + "'remote-no-fallback': '//:remote-no-fallback', "
        + "'remote-fallback': '//:remote-fallback',"
        "'remote-bad-fallback': '//:remote-bad-fallback'}"
    )
    rule_runner.set_options([env_names_arg, "--remote-execution"])
    assert get_name(LOCAL_ENVIRONMENT_MATCHER).val == "local"
    for name in ("local", "docker", "remote-no-fallback", "remote-fallback"):
        assert get_name(name).val == name
    with engine_error(UnrecognizedEnvironmentError):
        get_name("fake")

    assert get_name("local-fallback").val == "local"

    rule_runner.set_options([env_names_arg, "--no-remote-execution"])
    assert get_name("remote-fallback").val == "docker"
    with engine_error(NoFallbackEnvironmentError):
        get_name("remote-no-fallback")
    with engine_error(UnrecognizedEnvironmentError):
        get_name("remote-bad-fallback")


def test_resolve_environment_names(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                local_environment(name='local1')
                local_environment(name='local2')
                """
            )
        }
    )

    def get_names(v: Sequence[str]) -> EnvironmentName:
        return rule_runner.request(
            EnvironmentName, [SingleEnvironmentNameRequest(tuple(v), description_of_origin="foo")]
        )

    # If `--names` is not set, and the local matcher is used, do not choose an environment.
    assert get_names([LOCAL_ENVIRONMENT_MATCHER]).val is None

    env_names_arg = (
        "--environments-preview-names={" + "'local1': '//:local1', " + "'local2': '//:local2'}"
    )
    rule_runner.set_options([env_names_arg])

    assert get_names(["local1", "local1"]).val == "local1"

    with engine_error(contains="Needed 1 unique environment, but foo contained 2:"):
        _ = get_names(["local1", "local2"])


def test_resolve_environment_name_local_and_docker_fallbacks(monkeypatch) -> None:
    # We can't monkeypatch the Platform with RuleRunner, so instead use run_run_with_mocks.
    def get_env_name(
        env_tgt: Target, platform: Platform, *, docker_execution: bool = True
    ) -> str | None:
        monkeypatch.setattr(Platform, "create_for_localhost", lambda: platform)
        result = run_rule_with_mocks(
            resolve_environment_name,
            rule_args=[
                EnvironmentNameRequest("env", description_of_origin="foo"),
                create_subsystem(EnvironmentsSubsystem, names={"env": "", "fallback": ""}),
                create_subsystem(
                    GlobalOptions, remote_execution=False, docker_execution=docker_execution
                ),
            ],
            mock_gets=[
                MockGet(
                    output_type=ChosenLocalEnvironmentName,
                    input_types=(),
                    mock=lambda: ChosenLocalEnvironmentName(EnvironmentName(None)),
                ),
                MockGet(
                    output_type=ChosenLocalWorkspaceEnvironmentName,
                    input_types=(),
                    mock=lambda: ChosenLocalEnvironmentName(EnvironmentName(None)),
                ),
                MockGet(
                    output_type=EnvironmentTarget,
                    input_types=(EnvironmentName,),
                    mock=lambda name: EnvironmentTarget(name.val or "__local__", env_tgt),
                ),
                MockGet(
                    output_type=EnvironmentName,
                    input_types=(EnvironmentNameRequest,),
                    mock=lambda req: EnvironmentName(req.raw_value),
                ),
            ],
        ).val
        return result

    def create_local_tgt(
        *, compatible_platforms: list[Platform] | None = None, fallback: bool = False
    ) -> LocalEnvironmentTarget:
        return LocalEnvironmentTarget(
            {
                CompatiblePlatformsField.alias: [plat.value for plat in compatible_platforms]
                if compatible_platforms
                else None,
                FallbackEnvironmentField.alias: "fallback" if fallback else None,
            },
            Address("envs"),
        )

    assert get_env_name(create_local_tgt(), Platform.linux_arm64) == "env"
    assert (
        get_env_name(
            create_local_tgt(compatible_platforms=[Platform.linux_x86_64], fallback=True),
            Platform.linux_arm64,
        )
        == "fallback"
    )
    with pytest.raises(NoFallbackEnvironmentError):
        get_env_name(
            create_local_tgt(compatible_platforms=[Platform.linux_x86_64]),
            Platform.linux_arm64,
        )

    def create_docker_tgt(
        *, platform: Platform | None = None, fallback: bool = False
    ) -> DockerEnvironmentTarget:
        return DockerEnvironmentTarget(
            {
                DockerImageField.alias: "image",
                DockerPlatformField.alias: platform.value if platform else None,
                FallbackEnvironmentField.alias: "fallback" if fallback else None,
            },
            Address("envs"),
        )

    # If the Docker platform is not set, we default to the CPU arch. So regardless of localhost,
    # the Docker environment should be used.
    assert get_env_name(create_docker_tgt(), Platform.linux_arm64) == "env"

    # If Docker execution is disabled, though, fallback.
    assert (
        get_env_name(create_docker_tgt(fallback=True), Platform.linux_arm64, docker_execution=False)
        == "fallback"
    )
    with pytest.raises(NoFallbackEnvironmentError):
        get_env_name(create_docker_tgt(), Platform.linux_arm64, docker_execution=False)

    # The Docker env can be used if we're on macOS, or on Linux and the CPU arch matches.
    for plat in (Platform.macos_arm64, Platform.macos_x86_64, Platform.linux_x86_64):
        assert get_env_name(create_docker_tgt(platform=Platform.linux_x86_64), plat) == "env"
    for plat in (Platform.macos_arm64, Platform.macos_x86_64, Platform.linux_arm64):
        assert get_env_name(create_docker_tgt(platform=Platform.linux_arm64), plat) == "env"

    # But if on Linux and a different CPU arch is used, fallback.
    assert (
        get_env_name(
            create_docker_tgt(platform=Platform.linux_x86_64, fallback=True), Platform.linux_arm64
        )
        == "fallback"
    )
    assert (
        get_env_name(
            create_docker_tgt(platform=Platform.linux_arm64, fallback=True), Platform.linux_x86_64
        )
        == "fallback"
    )
    with pytest.raises(NoFallbackEnvironmentError):
        get_env_name(create_docker_tgt(platform=Platform.linux_x86_64), Platform.linux_arm64)
    with pytest.raises(NoFallbackEnvironmentError):
        get_env_name(create_docker_tgt(platform=Platform.linux_arm64), Platform.linux_x86_64)


def test_resolve_environment_tgt(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": "local_environment(name='env')"})
    rule_runner.set_options(
        ["--environments-preview-names={'env': '//:env', 'bad-address': '//:fake'}"]
    )

    def get_tgt(v: str | None) -> EnvironmentTarget:
        return rule_runner.request(EnvironmentTarget, [EnvironmentName(v)])

    assert get_tgt(None).val is None

    # If the name is not defined, error.
    with engine_error(AssertionError):
        get_tgt("bad")

    assert get_tgt("env").val.address == Address("", target_name="env")  # type: ignore[union-attr]
    with engine_error(ResolveError):
        get_tgt("bad-address")


def test_environment_name_request_from_field_set() -> None:
    class EnvFieldSubclass(EnvironmentField):
        alias = "the_env_field"  # This intentionally uses a custom alias.

    class Tgt(Target):
        alias = "tgt"
        help = "foo"
        core_fields = (OptionalSingleSourceField, EnvFieldSubclass)

    @dataclass(frozen=True)
    class NoEnvFS(FieldSet):
        required_fields = (OptionalSingleSourceField,)

        source: OptionalSingleSourceField

    @dataclass(frozen=True)
    class EnvFS(FieldSet):
        required_fields = (OptionalSingleSourceField,)

        source: OptionalSingleSourceField
        the_env_field: EnvironmentField  # This intentionally uses an unusual attribute name.

    tgt = Tgt({EnvFieldSubclass.alias: "my_env"}, Address("dir"))
    assert EnvironmentNameRequest.from_field_set(NoEnvFS.create(tgt)) == EnvironmentNameRequest(
        LOCAL_ENVIRONMENT_MATCHER,
        description_of_origin="the `environment` field from the target dir:dir",
    )
    assert EnvironmentNameRequest.from_field_set(EnvFS.create(tgt)) == EnvironmentNameRequest(
        "my_env", description_of_origin="the `the_env_field` field from the target dir:dir"
    )


def test_executable_search_path_cache_scope() -> None:
    def assert_cache(
        tgt: Target | None, *, cache_failures: bool, expected: ProcessCacheScope
    ) -> None:
        assert (
            EnvironmentTarget("unused", tgt).executable_search_path_cache_scope(
                cache_failures=cache_failures
            )
            == expected
        )

    addr = Address("envs")

    for tgt in (
        None,
        LocalEnvironmentTarget({}, addr),
        RemoteEnvironmentTarget({RemoteEnvironmentCacheBinaryDiscovery.alias: False}, addr),
    ):
        assert_cache(tgt, cache_failures=False, expected=ProcessCacheScope.PER_RESTART_SUCCESSFUL)
        assert_cache(tgt, cache_failures=True, expected=ProcessCacheScope.PER_RESTART_ALWAYS)

    for tgt in (  # type: ignore[assignment]
        DockerEnvironmentTarget({DockerImageField.alias: "img"}, addr),
        RemoteEnvironmentTarget({RemoteEnvironmentCacheBinaryDiscovery.alias: True}, addr),
    ):
        assert_cache(tgt, cache_failures=False, expected=ProcessCacheScope.SUCCESSFUL)
        assert_cache(tgt, cache_failures=True, expected=ProcessCacheScope.ALWAYS)


# Test for regression in choosing local environments.
def test_find_chosen_local_and_workspace_environments(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
            local_environment(name="local")
            workspace_environment(name="workspace")
            """
            )
        }
    )
    rule_runner.set_options(
        ["--environments-preview-names={'local': '//:local', 'workspace': '//:workspace'}"]
    )

    chosen_local_env = rule_runner.request(ChosenLocalEnvironmentName, [])
    assert chosen_local_env.val.val == "local"

    chosen_workspace_env = rule_runner.request(ChosenLocalWorkspaceEnvironmentName, [])
    assert chosen_workspace_env.val.val == "workspace"
