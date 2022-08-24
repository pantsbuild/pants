# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing_extensions import TypedDict

from pants.engine.internals.native_engine import (  # noqa: F401 # explicit re-export
    FilespecMatcher as FilespecMatcher,
)


class _IncludesDict(TypedDict, total=True):
    includes: list[str]


class Filespec(_IncludesDict, total=False):
    """A dict of includes (required) and excludes (optional).

    For example: {'includes': ['helloworld/*.py'], 'excludes': ['helloworld/ignore.py']}.

    The globs are in zglobs format.
    """

    excludes: list[str]
