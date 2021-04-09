# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from typing_extensions import TypedDict

from pants.engine.fs import PathGlobs
from pants.engine.internals import native_engine


class _IncludesDict(TypedDict, total=True):
    includes: list[str]


class Filespec(_IncludesDict, total=False):
    """A dict of includes (required) and excludes (optional).

    For example: {'includes': ['helloworld/*.py'], 'excludes': ['helloworld/ignore.py']}.

    The globs are in zglobs format.
    """

    excludes: list[str]


def matches_filespec(spec: Filespec, *, paths: Iterable[str]) -> tuple[str, ...]:
    include_patterns = spec["includes"]
    exclude_patterns = [f"!{e}" for e in spec.get("excludes", [])]
    return tuple(
        native_engine.match_path_globs(
            PathGlobs((*include_patterns, *exclude_patterns)), tuple(paths)
        )
    )
