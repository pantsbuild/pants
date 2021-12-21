# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo, DockerfileInfoRequest
from pants.backend.docker.subsystems.dockerfile_parser import rules as parser_rules
from pants.backend.docker.subsystems.dockerfile_parser import split_iterable
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.backend.docker.util_rules.dockerfile import rules as dockerfile_rules
from pants.backend.python.target_types import PexBinary
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
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
def test_putative_target_addresses(files: list[tuple[str, str]], rule_runner: RuleRunner) -> None:
    dockerfile_content = dedent(
        """\
        FROM base
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
    assert info.putative_target_addresses == (
        "some/target:binary",
        "some/target:tool",
        "another:cli",
    )


def test_split_iterable() -> None:
    assert [("a", "b"), ("c",)] == list(split_iterable("-", ("a", "b", "-", "c")))


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
    assert info.copy_sources == ("a", "b", "c/d", "e/f/g", "j", "k")
