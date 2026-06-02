# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.jvm.resolve.coordinate import Coordinate


@pytest.mark.parametrize(
    ("coord", "expected"),
    [
        (
            Coordinate(group="org.scala-lang", artifact="scala-library", version="2.13.18"),
            "org.scala-lang:scala-library:2.13.18",
        ),
        (
            Coordinate(
                group="com.example", artifact="foo", version="1.0", packaging="pom"
            ),
            "com.example:foo:1.0,type=pom",
        ),
    ],
)
def test_to_coord_arg_str_default_and_packaging(coord: Coordinate, expected: str) -> None:
    """Regression guards for the existing happy paths."""
    assert coord.to_coord_arg_str() == expected


def test_to_coord_arg_str_emits_type_jar_when_classifier_set() -> None:
    """A `classifier=sources` coord with default packaging needs `type=jar` in
    the Coursier arg string, otherwise `cs fetch --intransitive` returns an
    empty dependency list.

    Empirically confirmed against `cs` v2.1.14:
        $ cs fetch --intransitive 'org.scala-lang:scala-library:2.13.18,classifier=sources'
        # returns: {"dependencies":[]}
        $ cs fetch --intransitive 'org.scala-lang:scala-library:2.13.18,type=jar,classifier=sources'
        # returns: a real dependency with the sources jar path
    """
    coord = Coordinate(
        group="org.scala-lang",
        artifact="scala-library",
        version="2.13.18",
        classifier="sources",
    )
    arg = coord.to_coord_arg_str()
    assert "classifier=sources" in arg
    assert "type=jar" in arg


def test_to_coord_arg_str_emits_only_type_for_non_default_packaging() -> None:
    """A non-jar packaging with no classifier produces only `type=<packaging>` —
    no spurious `classifier=` attribute."""
    coord = Coordinate(
        group="com.example", artifact="foo", version="1.0", packaging="aar"
    )
    arg = coord.to_coord_arg_str()
    assert "type=aar" in arg
    assert "classifier" not in arg


def test_to_coord_arg_str_respects_extra_attrs() -> None:
    """Extra attrs are emitted alongside packaging/classifier without dropping
    either."""
    coord = Coordinate(
        group="com.example", artifact="foo", version="1.0", classifier="sources"
    )
    arg = coord.to_coord_arg_str(extra_attrs={"url": "file:/tmp/foo.jar"})
    assert "url=file:/tmp/foo.jar" in arg
    assert "type=jar" in arg
    assert "classifier=sources" in arg
