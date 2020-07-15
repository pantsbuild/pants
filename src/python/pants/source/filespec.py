# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable, List, Tuple

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


def matches_filespec(spec: Filespec, *, paths: Iterable[str]) -> Tuple[str, ...]:
    include_patterns = spec["includes"]
    exclude_patterns = [f"!{e}" for e in spec.get("excludes", [])]
    return Native().match_path_globs(PathGlobs(globs=(*include_patterns, *exclude_patterns)), paths)
