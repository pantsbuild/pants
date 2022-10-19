# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.engine.fs import EMPTY_DIGEST
from pants.jvm.shading.rules import ShadeJarRequest
from pants.jvm.target_types import (
    JarShadingKeepRule,
    JarShadingRelocateRule,
    JarShadingRenameRule,
    JarShadingRule,
    JarShadingZapRule,
)


def _expected_invalid_char_msg(name: str, invalid_char: str) -> str:
    def escape_char(ch: str) -> str:
        if ch == "*" or ch == "/" or ch == ".":
            return f"\\{ch}"
        return ch

    msg = f"`{name}` can not contain the character `{invalid_char}`"
    return str([escape_char(ch) for ch in msg])


@pytest.mark.parametrize(
    "rule, match",
    [
        (
            JarShadingRelocateRule(package="my/package", into="other.package"),
            _expected_invalid_char_msg("package", "/"),
        ),
        (
            JarShadingRelocateRule(package="my.package.*", into="other.package"),
            _expected_invalid_char_msg("package", "*"),
        ),
        (
            JarShadingRelocateRule(package="my.package", into="other/package"),
            _expected_invalid_char_msg("into", "/"),
        ),
        (
            JarShadingRelocateRule(package="my.package.*", into="other.package.*"),
            _expected_invalid_char_msg("into", "*"),
        ),
        (
            JarShadingRenameRule(pattern="my/package", replacement="other.package"),
            _expected_invalid_char_msg("pattern", "/"),
        ),
        (
            JarShadingRenameRule(pattern="my.package", replacement="other/package"),
            _expected_invalid_char_msg("replacement", "/"),
        ),
        (JarShadingZapRule(pattern="my/package"), _expected_invalid_char_msg("pattern", "/")),
        (JarShadingKeepRule(pattern="my/package"), _expected_invalid_char_msg("pattern", "/")),
    ],
)
def test_invalid_rules(rule: JarShadingRule, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        ShadeJarRequest(path="path/to/file", digest=EMPTY_DIGEST, rules=[rule])
