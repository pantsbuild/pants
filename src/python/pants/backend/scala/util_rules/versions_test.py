# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import pytest

from pants.backend.scala.util_rules.versions import ScalaCrossVersionMode, ScalaVersion


@pytest.mark.parametrize(
    "version_str, expected_obj, expected_binary",
    [
        ("2.12.0", ScalaVersion(2, 12, 0), "2.12"),
        ("3.3.1", ScalaVersion(3, 3, 1), "3"),
        ("3.0.1-RC2", ScalaVersion(3, 0, 1, "RC2"), "3"),
        ("2.13.8-jfhd8fyd834-SNAPSHOT", ScalaVersion(2, 13, 8, "jfhd8fyd834-SNAPSHOT"), "2.13"),
    ],
)
def test_scala_version_parser(
    version_str: str, expected_obj: ScalaVersion, expected_binary: str
) -> None:
    parsed = ScalaVersion.parse(version_str)
    assert parsed == expected_obj
    assert str(parsed) == version_str
    assert parsed.binary == expected_binary
    assert parsed.crossversion(ScalaCrossVersionMode.FULL) == version_str
    assert parsed.crossversion(ScalaCrossVersionMode.PARTIAL) == parsed.crossversion(
        ScalaCrossVersionMode.BINARY
    )
