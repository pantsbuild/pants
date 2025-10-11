# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from collections.abc import Iterable


def shlibdeps_filter_sonames(sonames: Iterable[str]) -> set[str]:
    """Filter any SONAMEs that dpkg-shlibdeps would ignore.

    dpkg-shlibdeps ignores:
      - SONAMEs that do not look like .so files
      - libm.so if libstdc++.so is already in deps
    dpkg-shlibdeps can also exclude deps based on command line args.
    Consuming rules are responsible for such exclusions, as this rule helper doesn't handle that.
    """
    sonames = tuple(sonames)  # this might be a generator, but this loops through it twice

    so_patt = re.compile(r"^.*\.so(\..*)?$")
    libm_patt = re.compile(r"^libm\.so\.\d+$")
    libstdcpp_patt = re.compile(r"^libstdc\+\+\.so\.\d+$")
    has_libstdcpp = any(libstdcpp_patt.match(soname) for soname in sonames)

    return {
        soname
        for soname in sonames
        if so_patt.match(soname) and (not has_libstdcpp or libm_patt.match(soname))
    }
