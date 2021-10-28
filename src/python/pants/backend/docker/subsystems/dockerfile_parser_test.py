# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from textwrap import dedent

import pytest

from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo
from pants.backend.docker.subsystems.dockerfile_parser import rules as parser_rules
from pants.backend.docker.subsystems.dockerfile_parser import split_iterable
from pants.backend.docker.target_types import (
    DockerfileTarget,
    DockerImageSourceField,
    DockerImageTarget,
)
from pants.backend.python.target_types import PexBinary
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *parser_rules(),
            *pex_rules(),
            *source_files_rules(),
            QueryRule(DockerfileInfo, (DockerImageSourceField,)),
        ],
        target_types=[DockerImageTarget, DockerfileTarget, PexBinary],
    )
    rule_runner.set_options(
        [],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


def test_putative_target_addresses(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/BUILD": "docker_image()",
            "test/Dockerfile": dedent(
                """\
            FROM base
            COPY some.target/binary.pex some.target/tool.pex /bin
            COPY --from=scratch this.is/ignored.pex /opt
            COPY binary another/cli.pex tool /bin
            """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("test"))
    info = rule_runner.request(DockerfileInfo, [tgt[DockerImageSourceField]])
    assert info.putative_target_addresses == (
        "some/target:binary",
        "some/target:tool",
        "another:cli",
    )


def test_split_iterable() -> None:
    assert [("a", "b"), ("c",)] == list(split_iterable("-", ("a", "b", "-", "c")))


def test_shadow_dockerfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/BUILD": dedent(
                """\
                docker_image(dependencies=[":dockerfile_a"])
                dockerfile(name="dockerfile_a", instructions=["FROM synth"])
                """
            ),
            "test/Dockerfile": "FROM disk",
        }
    )

    tgt = rule_runner.get_target(Address("test"))
    info = rule_runner.request(DockerfileInfo, [tgt[DockerImageSourceField]])
    assert info.source == "test/Dockerfile"
