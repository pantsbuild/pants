# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.subsystems.dockerfile_parser import (
    DockerfileAddress,
    DockerfileInfo,
    DockerfileInfoRequest,
)
from pants.backend.docker.subsystems.dockerfile_parser import rules as parser_rules
from pants.backend.docker.subsystems.dockerfile_parser import split_iterable
from pants.backend.docker.target_types import DockerfileTarget, DockerImageTarget
from pants.backend.docker.util_rules.dockerfile import rules as dockerfile_rules
from pants.backend.python.target_types import PexBinary
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import WrappedTarget
from pants.testutil.pytest_util import no_exception
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *dockerfile_rules(),
            *parser_rules(),
            *pex_rules(),
            QueryRule(DockerfileAddress, (WrappedTarget,)),
            QueryRule(DockerfileInfo, (DockerfileInfoRequest,)),
        ],
        target_types=[DockerImageTarget, DockerfileTarget, PexBinary],
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
                ("test/BUILD", 'docker_image(source="Dockerfile")'),
                ("test/Dockerfile", "{dockerfile}"),
            ],
            id="docker_image",
        ),
        pytest.param(
            [
                ("test/BUILD", "dockerfile(instructions=[{dockerfile!r}])"),
            ],
            id="dockerfile",
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


def test_parse_dockerfile_error(rule_runner: RuleRunner) -> None:
    rule_runner.create_file("test/BUILD", "docker_image()")
    with pytest.raises(
        ExecutionError, match=r"The `docker_image` test:test must have a single Dockerfile\."
    ):
        addr = Address("test")
        rule_runner.request(DockerfileInfo, [DockerfileInfoRequest(addr)])


def test_split_iterable() -> None:
    assert [("a", "b"), ("c",)] == list(split_iterable("-", ("a", "b", "-", "c")))


@pytest.mark.parametrize(
    "build_file, expected_address, expected_error",
    [
        pytest.param(
            "docker_image()",
            "test:test",
            no_exception(),
            id="Default is `docker_image`",
        ),
        pytest.param(
            'docker_image(source="Dockerfile")',
            "test:test",
            no_exception(),
            id="Dockerfile from workspace",
        ),
        pytest.param(
            dedent(
                """\
                docker_image(dependencies=[":dockerfile"])
                dockerfile(name="dockerfile", instructions=[])
                """
            ),
            "test:dockerfile",
            no_exception(),
            id="generated Dockerfile",
        ),
        pytest.param(
            dedent(
                """\
                docker_image(dependencies=[":gen1", ":gen2"])
                dockerfile(name="gen1", instructions=[])
                dockerfile(name="gen2", instructions=[])
                """
            ),
            None,
            pytest.raises(
                ExecutionError,
                match=(
                    r"The `docker_image` test:test may have at most one `dockerfile` dependency, "
                    r"but have 2: test:gen1, test:gen2\."
                ),
            ),
            id="Too many dockerfile dependencies",
        ),
        pytest.param(
            dedent(
                """\
                docker_image(source="Dockerfile", dependencies=[":dockerfile"])
                dockerfile(name="dockerfile", instructions=[])
                """
            ),
            None,
            pytest.raises(
                ExecutionError,
                match=(
                    r"The `docker_image` test:test must not provide both a `source` value and "
                    r"have a dependency to a `dockerfile` target at the same time\."
                ),
            ),
            id="conflicting Dockerfiles",
        ),
    ],
)
def test_resolve_dockerfile_address(
    rule_runner: RuleRunner, build_file: str, expected_address: str, expected_error
) -> None:
    rule_runner.create_file("test/BUILD", build_file)
    tgt = rule_runner.get_target(Address("test"))
    with expected_error:
        dockerfile_addr = rule_runner.request(DockerfileAddress, [WrappedTarget(tgt)])
        if expected_address:
            assert str(dockerfile_addr.address) == expected_address
