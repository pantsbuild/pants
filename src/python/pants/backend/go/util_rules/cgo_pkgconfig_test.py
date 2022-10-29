# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.backend.go.util_rules.cgo_pkgconfig import _split_pkg_config_output

# Adapted from the Go toolchain.
#
# Original copyright:
#   // Copyright 2011 The Go Authors. All rights reserved.
#   // Use of this source code is governed by a BSD-style
#   // license that can be found in the LICENSE file.


# Test casses adapted from https://github.com/golang/go/blob/54182ff54a687272dd7632c3a963e036ce03cb7c/src/cmd/go/internal/work/build_test.go#L38-L99
_TEST_CASES = [
    (
        rb"-r:foo -L/usr/white\ space/lib -lfoo\ bar -lbar\ baz",
        ("-r:foo", "-L/usr/white space/lib", "-lfoo bar", "-lbar baz"),
    ),
    (rb"-lextra\ fun\ arg\\", ("-lextra fun arg\\",)),
    (b"\textra     whitespace\r\n", ("extra", "whitespace")),
    (b"     \r\n      ", ()),
    (
        rb'''"-r:foo" "-L/usr/white space/lib" "-lfoo bar" "-lbar baz"''',
        ("-r:foo", "-L/usr/white space/lib", "-lfoo bar", "-lbar baz"),
    ),
    (rb'"-lextra fun arg\\"', ("-lextra fun arg\\",)),
    (rb'"     \r\n\      "', (r"     \r\n\      ",)),
    (rb'""', ()),
    (b"", ()),
    (b'''"\\\\"''', ("\\",)),
    (rb'"\x"', (r"\x",)),
    (rb'"\\x"', (r"\x",)),
    (b"""'\\\\'""", ("\\",)),
    (rb"'\x'", (r"\x",)),
    (rb'"\\x"', (r"\x",)),
    (
        rb"""-fPIC -I/test/include/foo -DQUOTED='"/test/share/doc"'""",
        ("-fPIC", "-I/test/include/foo", r'-DQUOTED="/test/share/doc"'),
    ),
    (
        rb'-fPIC -I/test/include/foo -DQUOTED="/test/share/doc"',
        ("-fPIC", "-I/test/include/foo", "-DQUOTED=/test/share/doc"),
    ),
    (
        rb"-fPIC -I/test/include/foo -DQUOTED=\"/test/share/doc\"",
        ("-fPIC", "-I/test/include/foo", r'-DQUOTED="/test/share/doc"'),
    ),
    (
        rb"-fPIC -I/test/include/foo -DQUOTED='/test/share/doc'",
        ("-fPIC", "-I/test/include/foo", "-DQUOTED=/test/share/doc"),
    ),
    (rb"""-DQUOTED='/te\st/share/d\oc'""", (r"-DQUOTED=/te\st/share/d\oc",)),
    (
        rb"-Dhello=10 -Dworld=+32 -DDEFINED_FROM_PKG_CONFIG=hello\ world",
        ("-Dhello=10", "-Dworld=+32", "-DDEFINED_FROM_PKG_CONFIG=hello world"),
    ),
    (rb'"broken\"" \\\a "a"', ('broken"', "\\a", "a")),
]


@pytest.mark.parametrize("pkgconfig_input,expected_output", _TEST_CASES)
def test_split_pkg_config_output(pkgconfig_input, expected_output) -> None:
    actual_output = _split_pkg_config_output(pkgconfig_input)
    assert expected_output == actual_output
