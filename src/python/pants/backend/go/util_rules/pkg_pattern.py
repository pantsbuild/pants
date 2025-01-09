# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import re
from typing import Callable

# Adapted from Go toolchain:
# https://github.com/golang/go/blob/6a70292d1cb3464e5b2c2c03341e5148730a1889/src/cmd/internal/pkgpattern/pkgpattern.go
#
# // Copyright 2022 The Go Authors. All rights reserved.
# // Use of this source code is governed by a BSD-style
# // license that can be found in the LICENSE file.


def match_pattern(pattern: str) -> Callable[[str], bool]:
    """MatchPattern(pattern)(name) reports whether name matches pattern. Pattern is a limited glob
    pattern in which '...' means 'any string' and there is no other special syntax. Unfortunately,
    there are two special cases. Quoting "go help packages":

    First, /... at the end of the pattern can match an empty string, so that net/... matches both
    net and packages in its subdirectories, like net/http. Second, any slash-separated pattern
    element containing a wildcard never participates in a match of the "vendor" element in the path
    of a vendored package, so that ./... does not match packages in subdirectories of ./vendor or
    ./mycode/vendor, but ./vendor/... and ./mycode/vendor/... do. Note, however, that a directory
    named vendor that itself contains code is not a vendored package: cmd/vendor would be a command
    named vendor, and the pattern cmd/... matches it.
    """
    return _match_pattern_internal(pattern, True)


def match_simple_pattern(pattern: str) -> Callable[[str], bool]:
    """MatchSimplePattern returns a function that can be used to check whether a given name matches
    a pattern, where pattern is a limited glob pattern in which '...' means 'any string', with no
    other special syntax.

    There is one special case for MatchPatternSimple: according to the rules in "go help packages":
    a /... at the end of the pattern can match an empty string, so that net/... matches both net and
    packages in its subdirectories, like net/http.
    """
    return _match_pattern_internal(pattern, False)


def _match_pattern_internal(pattern: str, vendor_exclude: bool) -> Callable[[str], bool]:
    # Convert pattern to regular expression.
    # The strategy for the trailing /... is to nest it in an explicit ? expression.
    # The strategy for the vendor exclusion is to change the unmatchable
    # vendor strings to a disallowed code point (vendorChar) and to use
    # "(anything but that codepoint)*" as the implementation of the ... wildcard.
    # This is a bit complicated, but the obvious alternative,
    # namely a handwritten search like in most shell glob matchers,
    # is too easy to make accidentally exponential.
    # Using package regexp guarantees linear-time matching.

    vendor_char = chr(0)  # "\x00"

    if vendor_exclude and vendor_char in pattern:
        return lambda _name: False

    r: str = re.escape(pattern)
    wild = ".*"
    if vendor_exclude:
        wild = rf"[^{vendor_char}]*"
        r = _replace_vendor(r, vendor_char)

        suffix = rf"/{vendor_char}/\.\.\."
        if r.endswith(suffix):
            r = r[0 : -len(suffix)] + rf"(/vendor|/{vendor_char}/\.\.\.)"
        elif r == rf"{vendor_char}/\.\.\.":
            r = rf"(/vendor|/{vendor_char}/\.\.\.)"

    suffix = r"/\.\.\."
    if r.endswith(suffix):
        r = r[0 : -len(suffix)] + r"(/\.\.\.)?"
    r = r.replace(r"\.\.\.", wild)

    reg = re.compile(rf"^{r}$")

    def f(name: str) -> bool:
        if vendor_exclude:
            if vendor_char in name:
                return False
            name = _replace_vendor(name, vendor_char)
        return bool(reg.match(name))

    return f


# replaceVendor returns the result of replacing
# non-trailing vendor path elements in x with repl.
def _replace_vendor(x: str, repl: str) -> str:
    if "vendor" not in x:
        return x

    elems = x.split("/")
    for i, elem in enumerate(elems[0:-1]):
        if elem == "vendor":
            elems[i] = repl
    return "/".join(elems)
