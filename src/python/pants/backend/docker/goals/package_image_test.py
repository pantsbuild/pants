# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Callable

import pytest

from pants.backend.docker.goals.package_image import (
    DockerFieldSet,
    DockerRepositoryNameError,
    build_docker_image,
)
from pants.backend.docker.registries import DockerRegistries
from pants.backend.docker.subsystems.docker_options import DockerEnvironmentVars, DockerOptions
from pants.backend.docker.subsystems.docker_options import rules as docker_options_rules
from pants.backend.docker.target_types import DockerImage
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
    DockerVersionContext,
    DockerVersionContextError,
    DockerVersionContextValue,
)
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, EMPTY_FILE_DIGEST
from pants.engine.process import Process, ProcessResult
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *docker_options_rules(),
            QueryRule(DockerEnvironmentVars, []),
            QueryRule(DockerOptions, []),
        ],
        target_types=[DockerImage],
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
        return DockerBuildContext(digest=EMPTY_DIGEST, version_context=DockerVersionContext())

    def run_process_mock(process: Process) -> ProcessResult:
        if process_assertions:
            process_assertions(process)

        return ProcessResult(
            stdout=b"stdout",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr=b"stderr",
            stderr_digest=EMPTY_FILE_DIGEST,
            output_digest=EMPTY_DIGEST,
        )

    if options:
        opts = options or {}
        opts.setdefault("registries", {})
        opts.setdefault("default_repository_name", "{directory}/{name}")
        opts.setdefault("build_args", [])
        opts.setdefault("env_vars", [])

        docker_options = create_subsystem(
            DockerOptions,
            **opts,
        )
    else:
        docker_options = rule_runner.request(DockerOptions, [])

    env = rule_runner.request(DockerEnvironmentVars, [])

    result = run_rule_with_mocks(
        build_docker_image,
        rule_args=[
            DockerFieldSet.create(tgt),
            docker_options,
            DockerBinary("/dummy/docker"),
            env,
        ],
        mock_gets=[
            MockGet(
                output_type=DockerBuildContext,
                input_type=DockerBuildContextRequest,
                mock=build_context_mock,
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
                  version="1.2.3",
                  repository_name="{directory}/{name}",
                )
                docker_image(
                  name="test2",
                  version="1.2.3"
                )
                docker_image(
                  name="test3",
                  version="1.2.3",
                  repository_name="{parent_directory}/{directory}/{name}",
                )
                docker_image(
                  name="test4",
                  version="1.2.3",
                  repository_name="{directory}/four/test-four",
                )
                docker_image(
                  name="test5",
                  image_tags=["alpha-1.0", "alpha-1"],
                )
                docker_image(
                  name="err1",
                  repository_name="{bad_template}",
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
        options=dict(default_repository_name="{directory}/{name}"),
    )

    err1 = (
        r"Invalid value for the `repository_name` field of the `docker_image` target at "
        r"docker/test:err1: '{bad_template}'\. Unknown key: 'bad_template'\.\n\n"
        r"You may only reference any of `name`, `directory` or `parent_directory`\."
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
                docker_image(name="addr1", version="1.2.3", registries=["myregistry1domain:port"])
                docker_image(name="addr2", version="1.2.3", registries=["myregistry2domain:port"])
                docker_image(name="addr3", version="1.2.3", registries=["myregistry3domain:port"])
                docker_image(name="alias1", version="1.2.3", registries=["@reg1"])
                docker_image(name="alias2", version="1.2.3", registries=["@reg2"])
                docker_image(name="alias3", version="1.2.3", registries=["reg3"])
                docker_image(name="unreg", version="1.2.3", registries=[])
                docker_image(name="def", version="1.2.3")
                docker_image(name="multi", version="1.2.3", registries=["@reg2", "@reg1"])
                """
            ),
            "docker/test/Dockerfile": "FROM python:3.8",
        }
    )

    options = {
        "default_repository_name": "{name}",
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
    version_context = DockerVersionContext(
        {
            "baseimage": DockerVersionContextValue({"tag": "3.8"}),
            "stage0": DockerVersionContextValue({"tag": "3.8"}),
            "interim": DockerVersionContextValue({"tag": "latest"}),
            "stage2": DockerVersionContextValue({"tag": "latest"}),
            "output": DockerVersionContextValue({"tag": "1-1"}),
        }
    )

    def assert_tags(name: str, *expect_tags: str) -> None:
        tgt = rule_runner.get_target(Address("docker/test", target_name=name))
        fs = DockerFieldSet.create(tgt)
        tags = fs.image_tags(
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
                  version="{baseimage.tag}-{stage2.tag}",
                  image_tags=["beta"]
                )
                docker_image(name="err_1", version="{unknown_stage}")
                docker_image(name="err_2", version="{stage0.unknown_value}")
                """
            ),
        }
    )

    assert_tags("ver_1", "image:latest")
    assert_tags("ver_2", "image:3.8-latest", "image:beta")

    err_1 = (
        r"Invalid format string for the `version` field of the `docker_image` target at "
        r"docker/test:err_1: '{unknown_stage}'\.\n\n"
        r"The key 'unknown_stage' is unknown\. Try with one of: baseimage, stage0, interim, "
        r"stage2, output\."
    )
    with pytest.raises(DockerVersionContextError, match=err_1):
        assert_tags("err_1")

    err_2 = (
        r"Invalid format string for the `version` field of the `docker_image` target at "
        r"docker/test:err_2: '{stage0.unknown_value}'\.\n\n"
        r"The key 'unknown_value' is unknown\. Try with one of: tag\."
    )
    with pytest.raises(DockerVersionContextError, match=err_2):
        assert_tags("err_2")


def test_docker_build_process_environment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"docker/test/BUILD": 'docker_image(name="env1", version="1.2.3")'})
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
    rule_runner.write_files({"docker/test/BUILD": 'docker_image(name="args1", version="1.2.3")'})
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
        {"docker/test/BUILD": 'docker_image(name="ver1", version="{build_args.VERSION}")'}
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
