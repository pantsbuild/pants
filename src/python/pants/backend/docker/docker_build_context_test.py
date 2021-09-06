# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Optional

import pytest

from pants.backend.docker.docker_build_context import DockerBuildContext, DockerBuildContextRequest
from pants.backend.docker.rules import rules
from pants.backend.docker.target_types import DockerImage
from pants.core.target_types import Files
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.fs import Snapshot
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            *source_files_rules(),
            QueryRule(DockerBuildContext, (DockerBuildContextRequest,)),
        ],
        target_types=[DockerImage, Files],
    )


def assert_build_context(
    rule_runner: RuleRunner,
    context_root: str,
    address: Address,
    expected_files: list[str],
    organize_context_tree: Optional[bool] = None,
) -> None:
    context = rule_runner.request(
        DockerBuildContext,
        [
            DockerBuildContextRequest(
                address=address,
                context_root=context_root,
                organize_context_tree=context_root != "."
                if organize_context_tree is None
                else organize_context_tree,
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
        "src/b",
        Address("src/b", target_name="img_B"),
        expected_files=["Dockerfile", "files/b01", "files/b02"],
    )

    # We want files_A in build context for img_A, but not files_B
    assert_build_context(
        rule_runner,
        "src/a",
        Address("src/a", target_name="img_A"),
        expected_files=["Dockerfile", "files/a01", "files/a02"],
    )

    # We want files_A in build context for img_A, but not files_B
    assert_build_context(
        rule_runner,
        ".",
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
        "src",
        Address("src/c", target_name="img_C"),
        expected_files=[
            "src/c/Dockerfile",
            "src/a/files/a01",
            "src/a/files/a02",
            "src/b/files/b01",
            "src/b/files/b02",
        ],
        organize_context_tree=False,
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
        "src/a",
        Address("src/a", target_name="img_A"),
        expected_files=[
            "Dockerfile",
            "res/static/s01",
            "res/static/s02",
            "res/static/sub/s03",
        ],
    )
