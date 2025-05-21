# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

from pants.backend.docker.lint.trivy.rules import TrivyDockerFieldSet, TrivyDockerRequest
from pants.backend.docker.lint.trivy.rules import rules as trivy_docker_rules
from pants.backend.docker.rules import rules as docker_rules
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.tools.trivy.rules import rules as trivy_rules
from pants.backend.tools.trivy.testutil import (
    assert_trivy_output,
    assert_trivy_success,
    trivy_config,
)
from pants.core.goals import package
from pants.core.goals.lint import LintResult
from pants.core.util_rules import source_files
from pants.core.util_rules.partitions import PartitionMetadata
from pants.engine.internals.native_engine import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    from pants.core.goals.lint import LintResult
    from pants.core.target_types import FileTarget

    rule_runner = RuleRunner(
        target_types=[DockerImageTarget, FileTarget],
        rules=[
            *trivy_docker_rules(),
            *trivy_rules(),
            *docker_rules(),
            *package.rules(),
            *source_files.rules(),
            QueryRule(LintResult, [TrivyDockerRequest.Batch]),
        ],
    )
    rule_runner.write_files(
        {
            "Dockerfile.good": GOOD_FILE,
            "Dockerfile.bad": BAD_FILE,
            "file.txt": "",
            "BUILD": dedent(
                """
            file(name="file", source="file.txt")
            docker_image(name="good", source="Dockerfile.good", dependencies=[":file"])
            docker_image(name="bad", source="Dockerfile.bad")
            """
            ),
            "trivy.yaml": trivy_config,
        }
    )
    # DOCKER_HOST allows for humans with rootless docker to run docker-dependent tests
    rule_runner.set_options(
        ("--trivy-extra-env-vars=DOCKER_HOST",),
        env_inherit={"PATH", "DOCKER_HOST"},
    )

    return rule_runner


GOOD_FILE = "FROM scratch\nCOPY file.txt /"  # A Docker image with nothing but a file is secure

BAD_FILE = (
    "FROM alpine:3.14.9@sha256:fa26727c28837d1471c2f1524d297a0255c153b5d023d7badd1412be7e6e12a2"
)
BAD_IMAGE_TARGET = "sha256:9e02963d7df7e8da13c08d23fd2f09b9dcf779422151766a8963415994e74ae0 (alpine 3.14.9)"  # this is Trivy's "Target" field


def test_trivy_good(rule_runner: RuleRunner) -> None:
    tgt_good = rule_runner.get_target(Address("", target_name="good"))

    result = rule_runner.request(
        LintResult,
        [
            TrivyDockerRequest.Batch(
                "trivy", (TrivyDockerFieldSet.create(tgt_good),), PartitionMetadata
            )
        ],
    )

    assert_trivy_success(result)


def test_trivy_bad(rule_runner: RuleRunner) -> None:
    tgt_bad = rule_runner.get_target(Address("", target_name="bad"))

    result = rule_runner.request(
        LintResult,
        [
            TrivyDockerRequest.Batch(
                "trivy", (TrivyDockerFieldSet.create(tgt_bad),), PartitionMetadata
            )
        ],
    )
    assert_trivy_output(result, 1, BAD_IMAGE_TARGET, "image", 4)
