# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pants.engine.fs import Digest
from pants.engine.unions import union


@union
class ToolLockfileSentinel:
    """Tools use this as an entry point to say how to generate their tool lockfile.

    Each language ecosystem should set up a union member of `LockfileRequest`, like
    `PythonLockfileRequest` and `CoursierLockfileRequest`. They should also set up a simple rule
    that goes from that class -> `WrappedLockfileRequest`.

    Then, each tool should subclass `ToolLockfileSentinel` and set up a rule that goes from the
    subclass -> the language's lockfile request, e.g. BlackLockfileSentinel ->
    PythonLockfileRequest. Register a union rule for the `ToolLockfileSentinel` subclass.
    """

    options_scope: ClassVar[str]


@dataclass(frozen=True)
class Lockfile:
    """The result of generating a lockfile for a particular resolve."""

    digest: Digest
    resolve_name: str
    path: str
