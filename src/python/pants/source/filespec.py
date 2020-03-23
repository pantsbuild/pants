# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable, List

from pants.engine.fs import PathGlobs
from pants.engine.native import Native
from pants.source.wrapped_globs import Filespec


def globs_matches(
    paths: Iterable[str], patterns: Iterable[str], exclude_patterns: Iterable[str],
) -> bool:
    path_globs = PathGlobs(globs=(*patterns, *(f"!{e}" for e in exclude_patterns)))
    return Native().match_path_globs(path_globs, paths)


def matches_filespec(path: str, spec: Filespec) -> bool:
    return any_matches_filespec([path], spec)


def any_matches_filespec(paths: Iterable[str], spec: Filespec) -> bool:
    exclude_patterns: List[str] = []
    for exclude_spec in spec.get("exclude", []):
        exclude_patterns.extend(exclude_spec["globs"])
    return globs_matches(paths, spec["globs"], exclude_patterns)
