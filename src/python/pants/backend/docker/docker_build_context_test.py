# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Callable

import pytest

from pants.backend.docker.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextPlugin,
    DockerBuildContextRequest,
)
from pants.backend.docker.rules import rules as docker_rules
from pants.backend.docker.target_types import DockerImage
from pants.core.target_types import Files
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestSubset,
    FileContent,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.rules import Get, MultiGet, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rules():
    return [
        *docker_rules(),
        *source_files_rules(),
        QueryRule(DockerBuildContext, (DockerBuildContextRequest,)),
    ]


@pytest.fixture
def rule_runner_factory(rules) -> Callable[..., RuleRunner]:
    def create_rule_runner(**kwargs) -> RuleRunner:
        if "rules" not in kwargs:
            kwargs["rules"] = rules
        if "target_types" not in kwargs:
            kwargs["target_types"] = [DockerImage, Files]
        return RuleRunner(**kwargs)

    return create_rule_runner


@pytest.fixture
def rule_runner(rule_runner_factory: Callable[..., RuleRunner]) -> RuleRunner:
    return rule_runner_factory()


def assert_build_context(
    rule_runner: RuleRunner,
    address: Address,
    expected_files: list[str],
) -> None:
    context = rule_runner.request(
        DockerBuildContext,
        [
            DockerBuildContextRequest(
                address=address,
                build_upstream_images=False,
            )
        ],
    )

    snapshot = rule_runner.request(Snapshot, [context.digest])
    assert sorted(expected_files) == sorted(snapshot.files)


def test_file_dependencies(rule_runner: RuleRunner) -> None:
    # img_A -> files_A
    # img_A -> img_B -> files_B
    rule_runner.add_to_build_file(
        "src/a",
        dedent(
            """\
            docker_image(name="img_A", dependencies=[":files_A", "src/b:img_B"])
            files(name="files_A", sources=["files/**"])
            """
        ),
    )
    rule_runner.add_to_build_file(
        "src/b",
        dedent(
            """\
            docker_image(name="img_B", dependencies=[":files_B"])
            files(name="files_B", sources=["files/**"])
            """
        ),
    )
    rule_runner.create_files("src/a", ["Dockerfile"])
    rule_runner.create_files("src/a/files", ["a01", "a02"])
    rule_runner.create_files("src/b", ["Dockerfile"])
    rule_runner.create_files("src/b/files", ["b01", "b02"])

    # We want files_B in build context for img_B
    assert_build_context(
        rule_runner,
        Address("src/b", target_name="img_B"),
        expected_files=["src/b/Dockerfile", "src/b/files/b01", "src/b/files/b02"],
    )

    # We want files_A in build context for img_A, but not files_B
    assert_build_context(
        rule_runner,
        Address("src/a", target_name="img_A"),
        expected_files=["src/a/Dockerfile", "src/a/files/a01", "src/a/files/a02"],
    )

    # Mixed.
    rule_runner.add_to_build_file(
        "src/c",
        dedent(
            """\
            docker_image(name="img_C", dependencies=["src/a:files_A", "src/b:files_B"])
            """
        ),
    )
    rule_runner.create_files("src/c", ["Dockerfile"])

    assert_build_context(
        rule_runner,
        Address("src/c", target_name="img_C"),
        expected_files=[
            "src/c/Dockerfile",
            "src/a/files/a01",
            "src/a/files/a02",
            "src/b/files/b01",
            "src/b/files/b02",
        ],
    )


def test_files_out_of_tree(rule_runner: RuleRunner) -> None:
    # src/a:img_A -> res/static:files
    rule_runner.add_to_build_file(
        "src/a",
        dedent(
            """\
            docker_image(name="img_A", dependencies=["res/static:files"])
            """
        ),
    )
    rule_runner.add_to_build_file(
        "res/static",
        dedent(
            """\
            files(name="files", sources=["!BUILD", "**/*"])
            """
        ),
    )
    rule_runner.create_files("src/a", ["Dockerfile"])
    rule_runner.create_files("res/static", ["s01", "s02"])
    rule_runner.create_files("res/static/sub", ["s03"])

    assert_build_context(
        rule_runner,
        Address("src/a", target_name="img_A"),
        expected_files=[
            "src/a/Dockerfile",
            "res/static/s01",
            "res/static/s02",
            "res/static/sub/s03",
        ],
    )


class CustomizeDockerBuildContext(DockerBuildContextPlugin):
    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        """Whether the build context plugin should be used for this target or not."""
        return True


@rule
async def customize_context(request: CustomizeDockerBuildContext) -> DockerBuildContext:
    droped_res2, res_injected = await MultiGet(
        # PathGlobs for subsetting is a little broken, so we use a really verbose set of patterns
        # here, to get around that. See issue #12863
        Get(
            Digest,
            DigestSubset(
                request.snapshot.digest,
                PathGlobs(["src/a/Dockerfile", "src/a/res/**", "!src/a/res/res2"]),
            ),
        ),
        Get(Digest, CreateDigest([FileContent("src/a/res/injected", b"stuffin")])),
    )
    context = await Get(Digest, MergeDigests([droped_res2, res_injected]))
    return DockerBuildContext(context)


def test_customize_context(rule_runner_factory: Callable[..., RuleRunner], rules) -> None:
    rule_runner = rule_runner_factory(
        rules=rules
        + [
            customize_context,
            UnionRule(DockerBuildContextPlugin, CustomizeDockerBuildContext),
        ],
    )
    rule_runner.write_files(
        {
            "src/a/BUILD": dedent(
                """\
            docker_image(name="a", dependencies=[":resources"])
            files(name="resources", sources=["res/**"])
            """
            ),
            "src/a/Dockerfile": "FROM python:3.8",
            "src/a/res/res1": "res1",
            "src/a/res/res2": "res2",
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/a", target_name="a"),
        expected_files=[
            "src/a/Dockerfile",
            "src/a/res/res1",
            "src/a/res/injected",
        ],
    )
