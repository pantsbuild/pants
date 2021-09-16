# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from textwrap import dedent

from pants.backend.docker.parser import DockerfileParser


def test_dockerfile_parser() -> None:
    parser = DockerfileParser(
        dedent(
            """\
            FROM base
            COPY some.target/binary.pex some.target/tool.pex /bin
            COPY --from=scratch this.is/ignored.pex /opt
            COPY binary another/cli.pex tool /bin
            """
        )
    )
    assert parser.putative_target_addresses() == (
        "some/target:binary",
        "some/target:tool",
        "another:cli",
    )
