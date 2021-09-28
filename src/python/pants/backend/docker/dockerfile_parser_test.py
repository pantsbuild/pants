# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from textwrap import dedent

import pytest

from pants.backend.docker.dockerfile_parser import ParsedDockerfile


def test_putative_target_addresses() -> None:
    parsed = ParsedDockerfile.parse(
        dedent(
            """\
            FROM base
            COPY some.target/binary.pex some.target/tool.pex /bin
            COPY --from=scratch this.is/ignored.pex /opt
            COPY binary another/cli.pex tool /bin
            """
        )
    )
    assert parsed.putative_target_addresses() == (
        "some/target:binary",
        "some/target:tool",
        "another:cli",
    )


@pytest.mark.parametrize(
    "copy_source, putative_target_address",
    [
        ("a/b", None),
        ("a/b.c", None),
        ("a.b", None),
        ("a.pex", ":a"),
        ("a/b.pex", "a:b"),
        ("a.b/c.pex", "a/b:c"),
        ("a.b.c/d.pex", "a/b/c:d"),
        ("a.b/c/d.pex", None),
        ("a/b/c.pex", None),
        ("a.0-1/b_2.pex", "a/0-1:b_2"),
        ("a#b/c.pex", None),
    ],
)
def test_translate_to_address(copy_source, putative_target_address) -> None:
    actual = ParsedDockerfile.translate_to_address(copy_source)
    assert actual == putative_target_address
