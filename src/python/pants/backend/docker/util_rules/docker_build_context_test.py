# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.subsystems.dockerfile_parser import rules as parser_rules
from pants.backend.docker.target_types import DockerfileTarget, DockerImageTarget
from pants.backend.docker.util_rules.docker_build_args import docker_build_args
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
    DockerVersionContext,
)
from pants.backend.docker.util_rules.docker_build_context import rules as context_rules
from pants.backend.docker.util_rules.docker_build_env import docker_build_environment_vars
from pants.backend.docker.util_rules.dockerfile import rules as dockerfile_rules
from pants.backend.python import target_types_rules
from pants.backend.python.goals import package_pex_binary
from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.target_types import PexBinary
from pants.backend.python.util_rules import pex_from_targets
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FilesGeneratorTarget
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.addresses import Address
from pants.engine.fs import Snapshot
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *context_rules(),
            *core_target_types_rules(),
            *dockerfile_rules(),
            *package_pex_binary.rules(),
            *parser_rules(),
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            docker_build_args,
            docker_build_environment_vars,
            QueryRule(BuiltPackage, [PexBinaryFieldSet]),
            QueryRule(DockerBuildContext, (DockerBuildContextRequest,)),
        ],
        target_types=[DockerImageTarget, DockerfileTarget, FilesGeneratorTarget, PexBinary],
    )
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


def assert_build_context(
    rule_runner: RuleRunner,
    address: Address,
    expected_files: list[str],
    expected_version_context: dict[str, dict[str, str]] | None = None,
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
    if expected_version_context is not None:
        assert context.version_context == DockerVersionContext.from_dict(expected_version_context)


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


def test_packaged_pex_path(rule_runner: RuleRunner) -> None:
    # This test is here to ensure that we catch if there is any change in the generated path where
    # built pex binaries go, as we rely on that for dependency inference in the Dockerfile.
    rule_runner.write_files(
        {
            "src/docker/BUILD": """docker_image(dependencies=["src/python/proj/cli:bin"])""",
            "src/docker/Dockerfile": """FROM python""",
            "src/python/proj/cli/BUILD": """pex_binary(name="bin", entry_point="main.py")""",
            "src/python/proj/cli/main.py": """print("cli main")""",
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/docker", target_name="docker"),
        expected_files=["src/docker/Dockerfile", "src.python.proj.cli/bin.pex"],
    )


def test_version_context_from_dockerfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/docker/BUILD": "docker_image()",
            "src/docker/Dockerfile": dedent(
                """\
                FROM python:3.8
                FROM alpine as interim
                FROM interim
                FROM scratch:1-1 as output
                """
            ),
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/docker"),
        expected_files=["src/docker/Dockerfile"],
        expected_version_context={
            "baseimage": {"tag": "3.8"},
            "stage0": {"tag": "3.8"},
            "interim": {"tag": "latest"},
            "stage2": {"tag": "latest"},
            "output": {"tag": "1-1"},
        },
    )


def test_synthetic_dockerfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/docker/BUILD": dedent(
                """\
                docker_image(source=":my-dockerfile")
                dockerfile(
                  name="my-dockerfile",
                  instructions=[
                    "FROM python:3.8",
                    "FROM alpine as interim",
                    "FROM interim",
                    "FROM scratch:1-1 as output",
                  ]
                )
                """
            ),
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/docker"),
        expected_files=["src.docker.my-dockerfile"],
        expected_version_context={
            "baseimage": {"tag": "3.8"},
            "stage0": {"tag": "3.8"},
            "interim": {"tag": "latest"},
            "stage2": {"tag": "latest"},
            "output": {"tag": "1-1"},
        },
    )
