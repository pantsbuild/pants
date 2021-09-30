# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.docker_binary import DockerBinary, DockerBinaryRequest
from pants.backend.docker.docker_build import DockerFieldSet, build_docker_image
from pants.backend.docker.docker_build_context import DockerBuildContext, DockerBuildContextRequest
from pants.backend.docker.subsystem import DockerOptions
from pants.backend.docker.target_types import DockerImage
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, EMPTY_FILE_DIGEST
from pants.engine.process import Process, ProcessResult
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, run_rule_with_mocks


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[],
        target_types=[DockerImage],
    )


def assert_build(
    rule_runner: RuleRunner, address: Address, *extra_log_lines: str, options: dict | None = None
) -> None:
    tgt = rule_runner.get_target(address)

    def build_context_mock(request: DockerBuildContextRequest) -> DockerBuildContext:
        return DockerBuildContext(digest=EMPTY_DIGEST)

    opts = options or {}
    opts.setdefault("registries", {})
    opts.setdefault("default_image_name_template", "{repository}/{name}")

    docker_options = create_subsystem(
        DockerOptions,
        **opts,
    )

    result = run_rule_with_mocks(
        build_docker_image,
        rule_args=[DockerFieldSet.create(tgt), docker_options],
        mock_gets=[
            MockGet(
                output_type=DockerBinary,
                input_type=DockerBinaryRequest,
                mock=lambda _: DockerBinary("/dummy/docker"),
            ),
            MockGet(
                output_type=DockerBuildContext,
                input_type=DockerBuildContextRequest,
                mock=build_context_mock,
            ),
            MockGet(
                output_type=ProcessResult,
                input_type=Process,
                # Process() generation has its own tests in test_docker_binary_build_image
                mock=lambda _: ProcessResult(
                    stdout=b"stdout",
                    stdout_digest=EMPTY_FILE_DIGEST,
                    stderr=b"stderr",
                    stderr_digest=EMPTY_FILE_DIGEST,
                    output_digest=EMPTY_DIGEST,
                ),
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
                  image_name_template="{name}",
                )
                docker_image(
                  name="test2",
                  version="1.2.3"
                )
                docker_image(
                  name="test3",
                  version="1.2.3",
                  image_name_template="{sub_repository}/{name}",
                )
                docker_image(
                  name="test4",
                  version="1.2.3",
                  image_name="test-four",
                  image_name_template="{sub_repository}/{name}",
                  repository="four",
                )
                docker_image(
                  name="test5",
                  image_tags=["alpha-1.0", "alpha-1"],
                )
                """
            ),
            "docker/test/Dockerfile": "FROM python:3.8",
        }
    )

    assert_build(
        rule_runner, Address("docker/test", target_name="test1"), "Built docker image: test1:1.2.3"
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="test2"),
        "Built docker image: test/test2:1.2.3",
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
        "default_image_name_template": "{name}",
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
