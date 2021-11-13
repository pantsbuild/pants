# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo, DockerfileInfoRequest
from pants.backend.docker.subsystems.dockerfile_parser import rules as parser_rules
from pants.backend.docker.subsystems.dockerfile_parser import split_iterable
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules.dockerfile import rules as dockerfile_rules
from pants.backend.python.target_types import PexBinary
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.engine.addresses import Address
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
