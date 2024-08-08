# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import typing
from hashlib import sha256
from unittest import mock

import pytest

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.docker_binary import DockerBinary, get_docker, rules
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.backend.experimental.docker.podman.register import rules as podman_rules
from pants.core.util_rules.system_binaries import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryShims,
    BinaryShimsRequest,
)
from pants.engine.fs import EMPTY_DIGEST, Digest, DigestEntries
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import QueryRule
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, run_rule_with_mocks


@pytest.fixture
def docker_path() -> str:
    return "/bin/docker"


@pytest.fixture
def docker(docker_path: str) -> DockerBinary:
    return DockerBinary(docker_path)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            *podman_rules(),
            QueryRule(DigestEntries, (Digest,)),
        ]
    )


def test_docker_binary_build_image(docker_path: str, docker: DockerBinary) -> None:
    dockerfile = "src/test/repo/Dockerfile"
    digest = Digest(sha256().hexdigest(), 123)
    tags = (
        "test:0.1.0",
        "test:latest",
    )
    env = {"DOCKER_HOST": "tcp://127.0.0.1:1234"}
    build_request = docker.build_image(
        tags=tags,
        digest=digest,
        dockerfile=dockerfile,
        build_args=DockerBuildArgs.from_strings("arg1=2"),
        context_root="build/context",
        env=env,
        use_buildx=False,
        extra_args=("--pull", "--squash"),
    )

    assert build_request == Process(
        argv=(
            docker_path,
            "build",
            "--pull",
            "--squash",
            "--tag",
            tags[0],
            "--tag",
            tags[1],
            "--build-arg",
            "arg1=2",
            "--file",
            dockerfile,
            "build/context",
        ),
        env=env,
        input_digest=digest,
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",  # The description field is marked `compare=False`
    )
    assert build_request.description == "Building docker image test:0.1.0 +1 additional tag."


def test_docker_binary_push_image(docker_path: str, docker: DockerBinary) -> None:
    image_ref = "registry/repo/name:tag"
    push_request = docker.push_image(image_ref)
    assert push_request == Process(
        argv=(docker_path, "push", image_ref),
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",  # The description field is marked `compare=False`
    )
    assert push_request.description == f"Pushing docker image {image_ref}"


def test_docker_binary_run_image(docker_path: str, docker: DockerBinary) -> None:
    image_ref = "registry/repo/name:tag"
    port_spec = "127.0.0.1:80:8080/tcp"
    run_request = docker.run_image(
        image_ref, docker_run_args=("-p", port_spec), image_args=("test-input",)
    )
    assert run_request == Process(
        argv=(docker_path, "run", "-p", port_spec, image_ref, "test-input"),
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",  # The description field is marked `compare=False`
    )
    assert run_request.description == f"Running docker image {image_ref}"


@pytest.mark.parametrize("podman_enabled", [True, False])
@pytest.mark.parametrize("podman_found", [True, False])
def test_get_docker(rule_runner: RuleRunner, podman_enabled: bool, podman_found: bool) -> None:
    docker_options = create_subsystem(
        DockerOptions,
        experimental_enable_podman=podman_enabled,
        tools=[],
        optional_tools=[],
    )
    docker_options_env_aware = mock.MagicMock(spec=DockerOptions.EnvironmentAware)

    def mock_get_binary_path(request: BinaryPathRequest) -> BinaryPaths:
        if request.binary_name == "podman" and podman_found:
            return BinaryPaths("podman", paths=[BinaryPath("/bin/podman")])

        elif request.binary_name == "docker":
            return BinaryPaths("docker", [BinaryPath("/bin/docker")])

        else:
            return BinaryPaths(request.binary_name, ())

    def mock_get_binary_shims(request: BinaryShimsRequest) -> BinaryShims:
        return BinaryShims(EMPTY_DIGEST, "cache_name")

    result = run_rule_with_mocks(
        get_docker,
        rule_args=[docker_options, docker_options_env_aware],
        mock_gets=[
            MockGet(
                output_type=BinaryPaths, input_types=(BinaryPathRequest,), mock=mock_get_binary_path
            ),
            MockGet(
                output_type=BinaryShims,
                input_types=(BinaryShimsRequest,),
                mock=mock_get_binary_shims,
            ),
        ],
    )

    if podman_enabled and podman_found:
        assert result.path == "/bin/podman"
        assert result.is_podman
    else:
        assert result.path == "/bin/docker"
        assert not result.is_podman


def test_get_docker_with_tools(rule_runner: RuleRunner) -> None:
    def mock_get_binary_path(request: BinaryPathRequest) -> BinaryPaths:
        if request.binary_name == "docker":
            return BinaryPaths("docker", paths=[BinaryPath("/bin/docker")])
        elif request.binary_name == "real-tool":
            return BinaryPaths("real-tool", paths=[BinaryPath("/bin/a-real-tool")])
        else:
            return BinaryPaths(request.binary_name, ())

    def mock_get_binary_shims(request: BinaryShimsRequest) -> BinaryShims:
        return BinaryShims(EMPTY_DIGEST, "cache_name")

    def run(tools: list[str], optional_tools: list[str]) -> DockerBinary:
        docker_options = create_subsystem(
            DockerOptions,
            experimental_enable_podman=False,
            tools=tools,
            optional_tools=optional_tools,
        )
        docker_options_env_aware = mock.MagicMock(spec=DockerOptions.EnvironmentAware)

        nonlocal mock_get_binary_path
        nonlocal mock_get_binary_shims

        result = run_rule_with_mocks(
            get_docker,
            rule_args=[docker_options, docker_options_env_aware],
            mock_gets=[
                MockGet(
                    output_type=BinaryPaths,
                    input_types=(BinaryPathRequest,),
                    mock=mock_get_binary_path,
                ),
                MockGet(
                    output_type=BinaryShims,
                    input_types=(BinaryShimsRequest,),
                    mock=mock_get_binary_shims,
                ),
            ],
        )

        return typing.cast(DockerBinary, result)

    run(tools=["real-tool"], optional_tools=[])

    with pytest.raises(BinaryNotFoundError, match="Cannot find `nonexistent-tool`"):
        run(tools=["real-tool", "nonexistent-tool"], optional_tools=[])

    # Optional non-existent tool should still succeed.
    run(tools=[], optional_tools=["real-tool", "nonexistent-tool"])
