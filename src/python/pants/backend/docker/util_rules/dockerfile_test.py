# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# from __future__ import annotations

from textwrap import dedent
from typing import Any, Mapping

import pytest

from pants.backend.docker.target_types import DockerImageSourceField, DockerImageTarget
from pants.backend.docker.util_rules.dockerfile import rules as dockerfile_rules
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents, FileContent
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import rule
from pants.engine.target import (
    GeneratedTargets,
    GenerateTargetsRequest,
    SourcesField,
    TargetGenerator,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner(request) -> RuleRunner:
    rule_runner_args: Mapping[str, Any] = dict(
        rules=[
            *dockerfile_rules(),
            *source_files_rules(),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[DockerImageTarget],
    )

    if hasattr(request, "param") and callable(request.param):
        request.param(rule_runner_args)

    return RuleRunner(**rule_runner_args)


DOCKERFILE = dedent(
    """\
    FROM python:3.9
    ENTRYPOINT python3
    """
)


def assert_dockerfile(
    rule_runner: RuleRunner,
    addr: Address = Address("test"),
    *,
    filename: str = "test/Dockerfile",
    content: str = DOCKERFILE,
) -> None:
    tgt = rule_runner.get_target(addr)
    result = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(
                sources_fields=[tgt.get(SourcesField)],
                for_sources_types=(DockerImageSourceField,),
                enable_codegen=True,
            )
        ],
    )

    if filename:
        assert result.snapshot.files == (filename,)

    if content:
        digest_contents = rule_runner.request(DigestContents, [result.snapshot.digest])
        assert len(digest_contents) == 1
        assert isinstance(digest_contents[0], FileContent)
        assert digest_contents[0].content.decode() == content


def test_hydrate_dockerfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/BUILD": "docker_image()",
            "test/Dockerfile": DOCKERFILE,
        }
    )
    assert_dockerfile(rule_runner)


def test_generate_dockerfile(rule_runner: RuleRunner) -> None:
    instructions = DOCKERFILE.strip().split("\n")
    rule_runner.write_files(
        {
            "test/BUILD": dedent(
                f"""\
                docker_image(
                  instructions={instructions!r},
                )
                """
            ),
        }
    )
    assert_dockerfile(rule_runner, filename="test/Dockerfile.test")


def setup_target_generator(rule_runner_args: dict) -> None:
    class GenerateOriginTarget(TargetGenerator):
        alias = "docker_image_generator"
        generated_target_cls = DockerImageTarget
        core_fields = ()
        copied_fields = ()
        moved_fields = ()

    class GenerateDockerImageTargetFromOrigin(GenerateTargetsRequest):
        generate_from = GenerateOriginTarget

    @rule
    async def generate_docker_image_rule(
        request: GenerateDockerImageTargetFromOrigin, union_membership: UnionMembership
    ) -> GeneratedTargets:
        return GeneratedTargets(
            request.generator,
            [
                DockerImageTarget(
                    {
                        "instructions": DOCKERFILE.strip().split("\n"),
                    },
                    request.template_address.create_generated("generated-image"),
                    union_membership,
                )
            ],
        )

    rule_runner_args["rules"].extend(
        [
            generate_docker_image_rule,
            UnionRule(GenerateTargetsRequest, GenerateDockerImageTargetFromOrigin),
        ]
    )
    rule_runner_args["target_types"].append(GenerateOriginTarget)


@pytest.mark.parametrize("rule_runner", [setup_target_generator], indirect=True)
def test_generate_dockerfile_for_generated_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/BUILD": "docker_image_generator()",
        }
    )
    assert_dockerfile(
        rule_runner,
        Address("test", generated_name="generated-image"),
        filename="test/Dockerfile.test.generated-image",
    )


def test_missing_dockerfile_is_error(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"test/BUILD": "docker_image()"})
    with pytest.raises(ExecutionError, match=r"The `docker_image` test:test does not specify any"):
        assert_dockerfile(rule_runner, filename="", content="")


def test_multiple_dockerfiles_is_error(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/BUILD": "docker_image(instructions=['FROM base'])",
            "test/Dockerfile": "FROM base",
        }
    )
    with pytest.raises(ExecutionError, match=r"The `docker_image` test:test provides both"):
        assert_dockerfile(rule_runner, filename="", content="")
