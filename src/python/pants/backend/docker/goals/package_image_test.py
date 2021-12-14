# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Callable

import pytest

from pants.backend.docker.goals.package_image import (
    DockerFieldSet,
    DockerImageTagValueError,
    DockerRepositoryNameError,
    build_docker_image,
    rules,
)
from pants.backend.docker.registries import DockerRegistries
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.backend.docker.util_rules.docker_build_args import (
    DockerBuildArgs,
    DockerBuildArgsRequest,
)
from pants.backend.docker.util_rules.docker_build_args import rules as build_args_rules
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
    DockerVersionContext,
)
from pants.backend.docker.util_rules.docker_build_env import (
    DockerBuildEnvironment,
    DockerBuildEnvironmentRequest,
)
from pants.backend.docker.util_rules.docker_build_env import rules as build_env_rules
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, EMPTY_FILE_DIGEST
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult, ProcessResultMetadata
from pants.engine.target import WrappedTarget
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            *build_args_rules(),
            *build_env_rules(),
            QueryRule(DockerOptions, []),
            QueryRule(DockerBuildArgs, [DockerBuildArgsRequest]),
            QueryRule(DockerBuildEnvironment, [DockerBuildEnvironmentRequest]),
        ],
        target_types=[DockerImageTarget],
    )


def assert_build(
    rule_runner: RuleRunner,
    address: Address,
    *extra_log_lines: str,
    options: dict | None = None,
    process_assertions: Callable[[Process], None] | None = None,
) -> None:
    tgt = rule_runner.get_target(address)

    def build_context_mock(request: DockerBuildContextRequest) -> DockerBuildContext:
        return DockerBuildContext.create(
            digest=EMPTY_DIGEST,
            dockerfile_info=DockerfileInfo(
                request.address, digest=EMPTY_DIGEST, source="docker/test/Dockerfile"
            ),
            build_args=rule_runner.request(DockerBuildArgs, [DockerBuildArgsRequest(tgt)]),
            build_env=rule_runner.request(
                DockerBuildEnvironment, [DockerBuildEnvironmentRequest(tgt)]
            ),
        )

    def run_process_mock(process: Process) -> ProcessResult:
        if process_assertions:
            process_assertions(process)

        return ProcessResult(
            stdout=b"stdout",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr=b"stderr",
            stderr_digest=EMPTY_FILE_DIGEST,
            output_digest=EMPTY_DIGEST,
            platform=Platform.current,
            metadata=ProcessResultMetadata(0, "ran_locally", 0),
        )

    if options:
        opts = options or {}
        opts.setdefault("registries", {})
        opts.setdefault("default_repository", "{directory}/{name}")
        opts.setdefault("build_args", [])
        opts.setdefault("env_vars", [])

        docker_options = create_subsystem(
            DockerOptions,
            **opts,
        )
    else:
        docker_options = rule_runner.request(DockerOptions, [])

    result = run_rule_with_mocks(
        build_docker_image,
        rule_args=[
            DockerFieldSet.create(tgt),
            docker_options,
            DockerBinary("/dummy/docker"),
        ],
        mock_gets=[
            MockGet(
                output_type=DockerBuildContext,
                input_type=DockerBuildContextRequest,
                mock=build_context_mock,
            ),
            MockGet(
                output_type=WrappedTarget,
                input_type=Address,
                mock=lambda _: WrappedTarget(tgt),
            ),
            MockGet(
                output_type=ProcessResult,
                input_type=Process,
                mock=run_process_mock,
            ),
        ],
    )

    assert result.digest == EMPTY_DIGEST
    assert len(result.artifacts) == 1
    assert result.artifacts[0].relpath is None

    for log_line in extra_log_lines:
        assert log_line in result.artifacts[0].extra_log_lines


def test_build_docker_image(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\

                docker_image(
                  name="test1",
                  image_tags=["1.2.3"],
                  repository="{directory}/{name}",
                )
                docker_image(
                  name="test2",
                  image_tags=["1.2.3"],
                )
                docker_image(
                  name="test3",
                  image_tags=["1.2.3"],
                  repository="{parent_directory}/{directory}/{name}",
                )
                docker_image(
                  name="test4",
                  image_tags=["1.2.3"],
                  repository="{directory}/four/test-four",
                )
                docker_image(
                  name="test5",
                  image_tags=["latest", "alpha-1.0", "alpha-1"],
                )
                docker_image(
                  name="err1",
                  repository="{bad_template}",
                )
                """
            ),
            "docker/test/Dockerfile": "FROM python:3.8",
        }
    )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="test1"),
        "Built docker image: test/test1:1.2.3",
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="test2"),
        "Built docker image: test2:1.2.3",
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="test3"),
        "Built docker image: docker/test/test3:1.2.3",
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="test4"),
        "Built docker image: test/four/test-four:1.2.3",
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="test5"),
        (
            "Built docker images: \n"
            "  * test/test5:latest\n"
            "  * test/test5:alpha-1.0\n"
            "  * test/test5:alpha-1"
        ),
        options=dict(default_repository="{directory}/{name}"),
    )

    err1 = (
        r"Invalid value for the `repository` field of the `docker_image` target at "
        r"docker/test:err1: '{bad_template}'\.\n\nThe placeholder 'bad_template' is unknown\. "
        r"Try with one of: directory, name, parent_directory\."
    )
    with pytest.raises(DockerRepositoryNameError, match=err1):
        assert_build(
            rule_runner,
            Address("docker/test", target_name="err1"),
        )


def test_build_image_with_registries(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(name="addr1", image_tags=["1.2.3"], registries=["myregistry1domain:port"])
                docker_image(name="addr2", image_tags=["1.2.3"], registries=["myregistry2domain:port"])
                docker_image(name="addr3", image_tags=["1.2.3"], registries=["myregistry3domain:port"])
                docker_image(name="alias1", image_tags=["1.2.3"], registries=["@reg1"])
                docker_image(name="alias2", image_tags=["1.2.3"], registries=["@reg2"])
                docker_image(name="alias3", image_tags=["1.2.3"], registries=["reg3"])
                docker_image(name="unreg", image_tags=["1.2.3"], registries=[])
                docker_image(name="def", image_tags=["1.2.3"])
                docker_image(name="multi", image_tags=["1.2.3"], registries=["@reg2", "@reg1"])
                """
            ),
            "docker/test/Dockerfile": "FROM python:3.8",
        }
    )

    options = {
        "default_repository": "{name}",
        "registries": {
            "reg1": {"address": "myregistry1domain:port"},
            "reg2": {"address": "myregistry2domain:port", "default": "true"},
        },
    }

    assert_build(
        rule_runner,
        Address("docker/test", target_name="addr1"),
        "Built docker image: myregistry1domain:port/addr1:1.2.3",
        options=options,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="addr2"),
        "Built docker image: myregistry2domain:port/addr2:1.2.3",
        options=options,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="addr3"),
        "Built docker image: myregistry3domain:port/addr3:1.2.3",
        options=options,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="alias1"),
        "Built docker image: myregistry1domain:port/alias1:1.2.3",
        options=options,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="alias2"),
        "Built docker image: myregistry2domain:port/alias2:1.2.3",
        options=options,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="alias3"),
        "Built docker image: reg3/alias3:1.2.3",
        options=options,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="unreg"),
        "Built docker image: unreg:1.2.3",
        options=options,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="def"),
        "Built docker image: myregistry2domain:port/def:1.2.3",
        options=options,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="multi"),
        (
            "Built docker images: \n"
            "  * myregistry2domain:port/multi:1.2.3\n"
            "  * myregistry1domain:port/multi:1.2.3"
        ),
        options=options,
    )


def test_dynamic_image_version(rule_runner: RuleRunner) -> None:
    version_context = DockerVersionContext.from_dict(
        {
            "baseimage": {"tag": "3.8"},
            "stage0": {"tag": "3.8"},
            "interim": {"tag": "latest"},
            "stage2": {"tag": "latest"},
            "output": {"tag": "1-1"},
        }
    )

    def assert_tags(name: str, *expect_tags: str) -> None:
        tgt = rule_runner.get_target(Address("docker/test", target_name=name))
        fs = DockerFieldSet.create(tgt)
        tags = fs.image_refs(
            "image",
            DockerRegistries.from_dict({}),
            version_context,
        )
        assert expect_tags == tags

    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(name="ver_1")
                docker_image(
                  name="ver_2",
                  image_tags=["{baseimage.tag}-{stage2.tag}", "beta"]
                )
                docker_image(name="err_1", image_tags=["{unknown_stage}"])
                docker_image(name="err_2", image_tags=["{stage0.unknown_value}"])
                """
            ),
        }
    )

    assert_tags("ver_1", "image:latest")
    assert_tags("ver_2", "image:3.8-latest", "image:beta")

    err_1 = (
        r"Invalid tag value for the `image_tags` field of the `docker_image` target at "
        r"docker/test:err_1: '{unknown_stage}'\.\n\n"
        r"The placeholder 'unknown_stage' is unknown\. Try with one of: baseimage, interim, "
        r"output, stage0, stage2\."
    )
    with pytest.raises(DockerImageTagValueError, match=err_1):
        assert_tags("err_1")

    err_2 = (
        r"Invalid tag value for the `image_tags` field of the `docker_image` target at "
        r"docker/test:err_2: '{stage0.unknown_value}'\.\n\n"
        r"The placeholder 'unknown_value' is unknown\. Try with one of: tag\."
    )
    with pytest.raises(DockerImageTagValueError, match=err_2):
        assert_tags("err_2")


def test_docker_build_process_environment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"docker/test/BUILD": 'docker_image(name="env1", image_tags=["1.2.3"])'}
    )
    rule_runner.set_options(
        [],
        env={
            "INHERIT": "from Pants env",
            "PANTS_DOCKER_ENV_VARS": '["VAR=value", "INHERIT"]',
        },
    )

    def check_docker_proc(process: Process):
        assert process.argv == (
            "/dummy/docker",
            "build",
            "-t",
            "env1:1.2.3",
            "-f",
            "docker/test/Dockerfile",
            ".",
        )
        assert process.env == FrozenDict(
            {
                "INHERIT": "from Pants env",
                "VAR": "value",
            }
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="env1"),
        process_assertions=check_docker_proc,
    )


def test_docker_build_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"docker/test/BUILD": 'docker_image(name="args1", image_tags=["1.2.3"])'}
    )
    rule_runner.set_options(
        [],
        env={
            "INHERIT": "from Pants env",
            "PANTS_DOCKER_BUILD_ARGS": '["VAR=value", "INHERIT"]',
        },
    )

    def check_docker_proc(process: Process):
        assert process.argv == (
            "/dummy/docker",
            "build",
            "-t",
            "args1:1.2.3",
            "--build-arg",
            "INHERIT",
            "--build-arg",
            "VAR=value",
            "-f",
            "docker/test/Dockerfile",
            ".",
        )

        # Check that we pull in name only args via env.
        assert process.env == FrozenDict(
            {
                "INHERIT": "from Pants env",
            }
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="args1"),
        process_assertions=check_docker_proc,
    )


def test_docker_image_version_from_build_arg(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"docker/test/BUILD": 'docker_image(name="ver1", image_tags=["{build_args.VERSION}"])'}
    )
    rule_runner.set_options(
        [],
        env={
            "PANTS_DOCKER_BUILD_ARGS": '["VERSION=1.2.3"]',
        },
    )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="ver1"),
        "Built docker image: ver1:1.2.3",
    )


def test_docker_repository_from_build_arg(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"docker/test/BUILD": 'docker_image(name="image", repository="{build_args.REPO}")'}
    )
    rule_runner.set_options(
        [],
        env={
            "PANTS_DOCKER_BUILD_ARGS": '["REPO=test/image"]',
        },
    )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="image"),
        "Built docker image: test/image:latest",
    )


def test_docker_extra_build_args_field(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  extra_build_args=[
                    "FROM_ENV",
                    "SET=value",
                    "DEFAULT2=overridden",
                  ]
                )
                """
            ),
        }
    )
    rule_runner.set_options(
        [
            "--docker-build-args=DEFAULT1=global1",
            "--docker-build-args=DEFAULT2=global2",
        ],
        env={
            "FROM_ENV": "env value",
            "SET": "no care",
        },
    )

    def check_docker_proc(process: Process):
        assert process.argv == (
            "/dummy/docker",
            "build",
            "-t",
            "img1:latest",
            "--build-arg",
            "DEFAULT1=global1",
            "--build-arg",
            "DEFAULT2=overridden",
            "--build-arg",
            "FROM_ENV",
            "--build-arg",
            "SET=value",
            "-f",
            "docker/test/Dockerfile",
            ".",
        )

        assert process.env == FrozenDict(
            {
                "FROM_ENV": "env value",
            }
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
    )


def test_docker_build_secrets_option(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  secrets={
                    "mysecret": "/var/run/secrets/mysecret",
                    "project-secret": "project/secrets/mysecret",
                  }
                )
                """
            ),
        }
    )

    def check_docker_proc(process: Process):
        assert process.argv == (
            "/dummy/docker",
            "build",
            "--secret=id=mysecret,src=/var/run/secrets/mysecret",
            f"--secret=id=project-secret,src={rule_runner.build_root}/docker/test/project/secrets/mysecret",
            "-t",
            "img1:latest",
            "-f",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
    )
