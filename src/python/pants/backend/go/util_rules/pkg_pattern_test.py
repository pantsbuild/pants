# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from typing import Callable

from pants.backend.go.util_rules.pkg_pattern import match_pattern, match_simple_pattern

# Adapted from Go toolchain:
# https://github.com/golang/go/blob/6a70292d1cb3464e5b2c2c03341e5148730a1889/src/cmd/internal/pkgpattern/pat_test.go
#
# // Copyright 2022 The Go Authors. All rights reserved.
# // Use of this source code is governed by a BSD-style
# // license that can be found in the LICENSE file.

_MATCH_PATTERN_TESTS = """
pattern ...
match foo

pattern net
match net
not net/http

pattern net/http
match net/http
not net

pattern net...
match net net/http netchan
not not/http not/net/http

# Special cases. Quoting docs:

# First, /... at the end of the pattern can match an empty string,
# so that net/... matches both net and packages in its subdirectories, like net/http.
pattern net/...
match net net/http
not not/http not/net/http netchan

# Second, any slash-separated pattern element containing a wildcard never
# participates in a match of the "vendor" element in the path of a vendored
# package, so that ./... does not match packages in subdirectories of
# ./vendor or ./mycode/vendor, but ./vendor/... and ./mycode/vendor/... do.
# Note, however, that a directory named vendor that itself contains code
# is not a vendored package: cmd/vendor would be a command named vendor,
# and the pattern cmd/... matches it.
pattern ./...
match ./vendor ./mycode/vendor
not ./vendor/foo ./mycode/vendor/foo

pattern ./vendor/...
match ./vendor/foo ./vendor/foo/vendor
not ./vendor/foo/vendor/bar

pattern mycode/vendor/...
match mycode/vendor mycode/vendor/foo mycode/vendor/foo/vendor
not mycode/vendor/foo/vendor/bar

pattern x/vendor/y
match x/vendor/y
not x/vendor

pattern x/vendor/y/...
match x/vendor/y x/vendor/y/z x/vendor/y/vendor x/vendor/y/z/vendor
not x/vendor/y/vendor/z

pattern .../vendor/...
match x/vendor/y x/vendor/y/z x/vendor/y/vendor x/vendor/y/z/vendor
"""


def test_match_pattern() -> None:
    _run_test(
        "match_pattern", _MATCH_PATTERN_TESTS, lambda pattern, name: match_pattern(pattern)(name)
    )


_MATCH_SIMPLE_PATTERN_TESTS = """
pattern ...
match foo

pattern .../bar/.../baz
match foo/bar/abc/baz

pattern net
match net
not net/http

pattern net/http
match net/http
not net

pattern net...
match net net/http netchan
not not/http not/net/http

# Special cases. Quoting docs:

# First, /... at the end of the pattern can match an empty string,
# so that net/... matches both net and packages in its subdirectories, like net/http.
pattern net/...
match net net/http
not not/http not/net/http netchan
"""


def test_simple_match_pattern() -> None:
    _run_test(
        "match_simple_pattern",
        _MATCH_SIMPLE_PATTERN_TESTS,
        lambda pattern, name: match_simple_pattern(pattern)(name),
    )


def _run_test(name: str, tests: str, fn: Callable[[str, str], bool]) -> None:
    patterns: list[str] = []
    for line in tests.splitlines():
        i = line.find("#")
        if i >= 0:
            line = line[:i]

        f = line.split()
        if len(f) == 0:
            continue

        if f[0] == "pattern":
            patterns = f[1:]
        elif f[0] in ("match", "not"):
            want = f[0] == "match"
            for pattern in patterns:
                for test_example in f[1:]:
                    result = fn(pattern, test_example)
                    assert (
                        result == want
                    ), f"{name}({pattern})({test_example}): result={result}, want={want}"
        else:
            raise ValueError(f"Unknown directive {f[0]}")
