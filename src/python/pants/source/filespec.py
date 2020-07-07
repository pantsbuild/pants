# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable, List

from typing_extensions import TypedDict

from pants.engine.fs import PathGlobs
from pants.engine.internals.native import Native


class _IncludesDict(TypedDict, total=True):
    includes: List[str]


class Filespec(_IncludesDict, total=False):
    """A dict of globs (required) and excludes (optional).

    For example: {'globs': ['helloworld/*.py'], 'exclude': ['helloworld/ignore.py']}.

    The globs are in zglobs format.
    """

    excludes: List[str]


def globs_matches(
    *, paths: Iterable[str], include_patterns: Iterable[str], exclude_patterns: Iterable[str],
) -> bool:
    path_globs = PathGlobs(globs=(*include_patterns, *(f"!{e}" for e in exclude_patterns)))
    return Native().match_path_globs(path_globs, paths)


def matches_filespec(spec: Filespec, *, path: str) -> bool:
    return any_matches_filespec(spec, paths=[path])


def any_matches_filespec(spec: Filespec, *, paths: Iterable[str]) -> bool:
    return globs_matches(
        paths=paths, include_patterns=spec["includes"], exclude_patterns=spec.get("excludes", [])
    )
