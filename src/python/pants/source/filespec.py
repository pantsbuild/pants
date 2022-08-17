# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from typing_extensions import TypedDict

from pants.base.deprecated import deprecated
from pants.engine.internals.native_engine import (
    FilespecMatcher as FilespecMatcher,  # explicit re-export
)


class _IncludesDict(TypedDict, total=True):
    includes: list[str]


class Filespec(_IncludesDict, total=False):
    """A dict of includes (required) and excludes (optional).

    For example: {'includes': ['helloworld/*.py'], 'excludes': ['helloworld/ignore.py']}.

    The globs are in zglobs format.
    """

    excludes: list[str]


@deprecated("2.15.0.dev0", "Use `FilespecMatcher().matches()` instead", start_version="2.14.0.dev5")
def matches_filespec(spec: Filespec, *, paths: Iterable[str]) -> tuple[str, ...]:
    matcher = FilespecMatcher(spec["includes"], spec.get("excludes", []))
    return tuple(matcher.matches(tuple(paths)))
