# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import namedtuple
from hashlib import sha256
from typing import cast
from unittest import mock

import pytest

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.binaries import (
    BuildctlBinary,
    DockerBinary,
    PodmanBinary,
    get_buildctl,
    get_docker,
    get_podman,
)
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.core.util_rules.system_binaries import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryShims,
    BinaryShimsRequest,
)
from pants.engine.fs import EMPTY_DIGEST, Digest
from pants.engine.process import Process, ProcessCacheScope
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import run_rule_with_mocks

BinaryInfo = namedtuple("BinaryInfo", ["cls", "path", "name"])


@pytest.fixture(
    params=[
        BinaryInfo(DockerBinary, "/bin/docker", "docker"),
        BinaryInfo(PodmanBinary, "/bin/podman", "podman"),
    ]
)
def binary_info(request) -> BinaryInfo:
    return cast(BinaryInfo, request.param)


@pytest.fixture
def binary_path(binary_info: BinaryInfo) -> str:
    return cast(str, binary_info.path)


@pytest.fixture
def binary(binary_info: BinaryInfo) -> DockerBinary | PodmanBinary:
    return cast(DockerBinary | PodmanBinary, binary_info.cls(binary_info.path))


@pytest.fixture
def buildctl_path() -> str:
    return "/bin/buildctl"


@pytest.fixture
def buildctl(buildctl_path: str) -> BuildctlBinary:
    return BuildctlBinary(buildctl_path)


def test_binary_build_image(binary_path: str, binary: DockerBinary | PodmanBinary) -> None:
    dockerfile = "src/test/repo/Dockerfile"
    digest = Digest(sha256().hexdigest(), 123)
    tags = (
        "test:0.1.0",
        "test:latest",
    )
    env = {"DOCKER_HOST": "tcp://127.0.0.1:1234"}
    build_request = binary.build_image(
        tags=tags,
        digest=digest,
        dockerfile=dockerfile,
        build_args=DockerBuildArgs.from_strings("arg1=2"),
        context_root="build/context",
        env=env,
        extra_args=("--pull", "--squash"),
        output={"type": "docker"},
        output_files=("dist/app",),
        output_directories=("reports",),
    )

    assert build_request == Process(
        argv=(
            binary_path,
            "build",
            "--pull",
            "--squash",
            "--output",
            "type=docker",
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
        output_files=("dist/app",),
        output_directories=("reports",),
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",  # The description field is marked `compare=False`
    )
    assert build_request.description == "Building docker image test:0.1.0 +1 additional tag."


def test_binary_push_image(binary_path: str, binary: DockerBinary | PodmanBinary) -> None:
    image_ref = "registry/repo/name:tag"
    push_request = binary.push_image(image_ref)
    assert push_request == Process(
        argv=(binary_path, "push", image_ref),
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",  # The description field is marked `compare=False`
    )
    assert push_request.description == f"Pushing docker image {image_ref}"


def test_binary_run_image(binary_path: str, binary: DockerBinary | PodmanBinary) -> None:
    image_ref = "registry/repo/name:tag"
    port_spec = "127.0.0.1:80:8080/tcp"
    run_request = binary.run_image(
        image_ref, docker_run_args=("-p", port_spec), image_args=("test-input",)
    )
    assert run_request == Process(
        argv=(binary_path, "run", "-p", port_spec, image_ref, "test-input"),
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",  # The description field is marked `compare=False`
    )
    assert run_request.description == f"Running docker image {image_ref}"


def test_buildctl_binary_build_image(buildctl_path: str, buildctl: BuildctlBinary) -> None:
    dockerfile = "src/test/repo/Dockerfile"
    digest = Digest(sha256().hexdigest(), 123)
    tags = (
        "test:0.1.0",
        "test:latest",
    )
    env = {"BUILDKIT_HOST": "tcp://127.0.0.1:1234"}
    build_request = buildctl.build_image(
        tags=tags,
        digest=digest,
        dockerfile=dockerfile,
        build_args=DockerBuildArgs.from_strings("arg1=2"),
        context_root="build/context",
        env=env,
        extra_args=("--progress=plain",),
        output=None,
    )

    assert build_request == Process(
        argv=(
            buildctl_path,
            "build",
            "--frontend",
            "dockerfile.v0",
            "--local",
            "context=build/context",
            "--local",
            "dockerfile=src/test/repo",
            "--opt",
            "filename=Dockerfile",
            "--progress=plain",
            "--opt",
            "build-arg:arg1=2",
            "--output",
            "type=image,name=test:0.1.0",
            "--output",
            "type=image,name=test:latest",
        ),
        env=env,
        input_digest=digest,
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",  # The description field is marked `compare=False`
    )
    assert build_request.description == "Building docker image test:0.1.0 +1 additional tag."


def test_buildctl_binary_build_image_publish(buildctl_path: str, buildctl: BuildctlBinary) -> None:
    dockerfile = "src/test/repo/Dockerfile"
    digest = Digest(sha256().hexdigest(), 123)
    tags = (
        "test:0.1.0",
        "test:latest",
    )
    build_request = buildctl.build_image(
        tags=tags,
        digest=digest,
        dockerfile=dockerfile,
        build_args=DockerBuildArgs(()),
        context_root="build/context",
        env={},
        output=None,
        is_publish=True,
    )

    assert build_request == Process(
        argv=(
            buildctl_path,
            "build",
            "--frontend",
            "dockerfile.v0",
            "--local",
            "context=build/context",
            "--local",
            "dockerfile=src/test/repo",
            "--opt",
            "filename=Dockerfile",
            "--output",
            "type=image,name=test:0.1.0,push=true",
            "--output",
            "type=image,name=test:latest,push=true",
        ),
        input_digest=digest,
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",
    )


def test_buildctl_binary_build_image_custom_output(
    buildctl_path: str, buildctl: BuildctlBinary
) -> None:
    dockerfile = "src/test/repo/Dockerfile"
    digest = Digest(sha256().hexdigest(), 123)
    tags = ("test:0.1.0",)
    build_request = buildctl.build_image(
        tags=tags,
        digest=digest,
        dockerfile=dockerfile,
        build_args=DockerBuildArgs(()),
        context_root=".",
        env={},
        output={"type": "image", "name": "custom:tag", "push": "true"},
    )

    assert build_request == Process(
        argv=(
            buildctl_path,
            "build",
            "--frontend",
            "dockerfile.v0",
            "--local",
            "context=.",
            "--local",
            "dockerfile=src/test/repo",
            "--opt",
            "filename=Dockerfile",
            "--output",
            "type=image,name=custom:tag,push=true",
        ),
        input_digest=digest,
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",
    )


def test_buildctl_binary_build_image_local_output(
    buildctl_path: str, buildctl: BuildctlBinary
) -> None:
    dockerfile = "src/test/repo/Dockerfile"
    digest = Digest(sha256().hexdigest(), 123)
    build_request = buildctl.build_image(
        tags=("test:0.1.0",),
        digest=digest,
        dockerfile=dockerfile,
        build_args=DockerBuildArgs(()),
        context_root=".",
        env={},
        output={"type": "local", "dest": "."},
        output_files=("bin/app",),
        output_directories=("share",),
    )

    assert build_request == Process(
        argv=(
            buildctl_path,
            "build",
            "--frontend",
            "dockerfile.v0",
            "--local",
            "context=.",
            "--local",
            "dockerfile=src/test/repo",
            "--opt",
            "filename=Dockerfile",
            "--output",
            "type=local,dest=.",
        ),
        input_digest=digest,
        output_files=("bin/app",),
        output_directories=("share",),
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="",
    )


@pytest.mark.parametrize(
    ["binary_name", "rule_func", "binary_cls"],
    [
        ("docker", get_docker, DockerBinary),
        ("podman", get_podman, PodmanBinary),
        ("buildctl", get_buildctl, BuildctlBinary),
    ],
)
def test_get_binary(binary_name, rule_func, binary_cls) -> None:
    docker_options = create_subsystem(
        DockerOptions,
        tools=[],
        optional_tools=[],
    )
    docker_options_env_aware = mock.MagicMock(spec=DockerOptions.EnvironmentAware)

    def mock_find_binary(request: BinaryPathRequest) -> BinaryPaths:
        if request.binary_name == binary_name:
            return BinaryPaths(binary_name, [BinaryPath(f"/bin/{binary_name}")])
        return BinaryPaths(request.binary_name, ())

    def mock_create_binary_shims(_request: BinaryShimsRequest) -> BinaryShims:
        return BinaryShims(EMPTY_DIGEST, "cache_name")

    result = run_rule_with_mocks(
        rule_func,
        rule_args=[docker_options, docker_options_env_aware],
        mock_calls={
            "pants.core.util_rules.system_binaries.find_binary": mock_find_binary,
            "pants.core.util_rules.system_binaries.create_binary_shims": mock_create_binary_shims,
        },
    )

    assert isinstance(result, binary_cls)
    assert result.path == f"/bin/{binary_name}"


@pytest.mark.parametrize(
    ["binary_name", "rule_func"],
    [
        ("docker", get_docker),
        ("podman", get_podman),
        ("buildctl", get_buildctl),
    ],
)
def test_get_binary_with_tools(binary_name, rule_func) -> None:
    def mock_find_binary(request: BinaryPathRequest) -> BinaryPaths:
        if request.binary_name == binary_name:
            return BinaryPaths(binary_name, paths=[BinaryPath(f"/bin/{binary_name}")])
        elif request.binary_name == "real-tool":
            return BinaryPaths("real-tool", paths=[BinaryPath("/bin/a-real-tool")])
        else:
            return BinaryPaths(request.binary_name, ())

    def mock_create_binary_shims(_request: BinaryShimsRequest) -> BinaryShims:
        return BinaryShims(EMPTY_DIGEST, "cache_name")

    def run(tools: list[str], optional_tools: list[str]) -> None:
        docker_options = create_subsystem(
            DockerOptions,
            tools=tools,
            optional_tools=optional_tools,
        )
        docker_options_env_aware = mock.MagicMock(spec=DockerOptions.EnvironmentAware)

        nonlocal mock_find_binary
        nonlocal mock_create_binary_shims

        run_rule_with_mocks(
            rule_func,
            rule_args=[docker_options, docker_options_env_aware],
            mock_calls={
                "pants.core.util_rules.system_binaries.find_binary": mock_find_binary,
                "pants.core.util_rules.system_binaries.create_binary_shims": mock_create_binary_shims,
            },
        )

    run(tools=["real-tool"], optional_tools=[])

    with pytest.raises(BinaryNotFoundError, match="Cannot find `nonexistent-tool`"):
        run(tools=["real-tool", "nonexistent-tool"], optional_tools=[])

    # Optional non-existent tool should still succeed.
    run(tools=[], optional_tools=["real-tool", "nonexistent-tool"])
