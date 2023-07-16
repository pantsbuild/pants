# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo, DockerfileInfoRequest
from pants.backend.docker.subsystems.dockerfile_parser import rules as parser_rules
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.backend.docker.util_rules.dockerfile import rules as dockerfile_rules
from pants.backend.python.target_types import PexBinary
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.pants_integration_test import run_pants
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *dockerfile_rules(),
            *parser_rules(),
            *pex_rules(),
            QueryRule(DockerfileInfo, (DockerfileInfoRequest,)),
        ],
        target_types=[DockerImageTarget, PexBinary],
    )
    rule_runner.set_options(
        [],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(
            [
                ("test/BUILD", "docker_image()"),
                ("test/Dockerfile", "{dockerfile}"),
            ],
            id="source Dockerfile",
        ),
        pytest.param(
            [
                ("test/BUILD", "docker_image(instructions=[{dockerfile!r}])"),
            ],
            id="generate Dockerfile",
        ),
    ],
)
def test_parsed_injectables(files: list[tuple[str, str]], rule_runner: RuleRunner) -> None:
    dockerfile_content = dedent(
        """\
        ARG BASE_IMAGE=:base
        FROM $BASE_IMAGE
        COPY some.target/binary.pex some.target/tool.pex /bin
        COPY --from=scratch this.is/ignored.pex /opt
        COPY binary another/cli.pex tool /bin
        """
    )

    rule_runner.write_files(
        {filename: content.format(dockerfile=dockerfile_content) for filename, content in files}
    )

    addr = Address("test")
    info = rule_runner.request(DockerfileInfo, [DockerfileInfoRequest(addr)])
    assert info.from_image_build_args.to_dict() == {"BASE_IMAGE": ":base"}
    assert info.copy_source_paths == (
        "some.target/binary.pex",
        "some.target/tool.pex",
        "binary",
        "another/cli.pex",
        "tool",
    )


def test_build_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/BUILD": "docker_image()",
            "test/Dockerfile": dedent(
                """\
                ARG registry
                FROM ${registry}/image:latest
                ARG OPT_A
                ARG OPT_B=default_b_value
                ENV A=${OPT_A:-A_value}
                ENV B=${OPT_B}
                """
            ),
        }
    )
    addr = Address("test")
    info = rule_runner.request(DockerfileInfo, [DockerfileInfoRequest(addr)])
    assert info.build_args == DockerBuildArgs.from_strings(
        "registry",
        "OPT_A",
        "OPT_B=default_b_value",
    )


def test_from_image_build_arg_names(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/upstream/BUILD": "docker_image(name='image')",
            "test/upstream/Dockerfile": "FROM upstream",
            "test/downstream/BUILD": "docker_image(name='image')",
            "test/downstream/Dockerfile": dedent(
                """\
                ARG BASE_IMAGE=test/upstream:image
                FROM ${BASE_IMAGE} AS base
                """
            ),
        }
    )
    addr = Address("test/downstream", target_name="image")
    info = rule_runner.request(DockerfileInfo, [DockerfileInfoRequest(addr)])
    assert info.from_image_build_args.to_dict() == {"BASE_IMAGE": "test/upstream:image"}


def test_inconsistent_build_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/BUILD": "docker_image(name='image')",
            "test/Dockerfile": dedent(
                """\
                FROM image1:latest
                ARG OPT_A=default_1

                FROM image2:latest
                ARG OPT_A=default_2
                """
            ),
        }
    )
    addr = Address("test", target_name="image")
    err_msg = (
        r"Error while parsing test/Dockerfile for the test:image target: DockerBuildArgs: "
        r"duplicated 'OPT_A' with different values: 'default_1' != 'default_2'\."
    )
    with pytest.raises(ExecutionError, match=err_msg):
        rule_runner.request(DockerfileInfo, [DockerfileInfoRequest(addr)])


def test_copy_source_references(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/BUILD": "docker_image()",
            "test/Dockerfile": dedent(
                """\
                FROM base
                COPY a b /
                COPY --option c/d e/f/g /h
                ADD ignored
                COPY j k /
                COPY
                """
            ),
        }
    )

    info = rule_runner.request(DockerfileInfo, [DockerfileInfoRequest(Address("test"))])
    assert info.copy_source_paths == ("a", "b", "c/d", "e/f/g", "j", "k")


def test_baseimage_tags(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/BUILD": "docker_image()",
            "test/Dockerfile": (
                "FROM untagged\n"
                "FROM tagged:v1.2\n"
                "FROM digest@sha256:d1f0463b35135852308ea815c2ae54c1734b876d90288ce35828aeeff9899f9d\n"
                "FROM gcr.io/tekton-releases/github.com/tektoncd/operator/cmd/kubernetes/operator:"
                "v0.54.0@sha256:d1f0463b35135852308ea815c2ae54c1734b876d90288ce35828aeeff9899f9d\n"
                "FROM $PYTHON_VERSION AS python\n"
            ),
        }
    )

    info = rule_runner.request(DockerfileInfo, [DockerfileInfoRequest(Address("test"))])
    assert info.version_tags == (
        "stage0 latest",
        "stage1 v1.2",
        # Stage 2 is not pinned with a tag.
        "stage3 v0.54.0",
        "python build-arg:PYTHON_VERSION",  # Parse tag from build arg.
    )


def test_generate_lockfile_without_python_backend() -> None:
    """Regression test for https://github.com/pantsbuild/pants/issues/14876."""
    run_pants(
        [
            "--backend-packages=pants.backend.docker",
            "--python-resolves={'dockerfile-parser':'dp.lock'}",
            "generate-lockfiles",
            "--resolve=dockerfile-parser",
        ]
    ).assert_success()
