# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pants.engine.fs import Digest
from pants.engine.unions import union


@dataclass(frozen=True)
class Lockfile:
    """The result of generating a lockfile for a particular resolve."""

    digest: Digest
    resolve_name: str
    path: str


@union
@dataclass(frozen=True)
class LockfileRequest:
    """A union base for generating ecosystem-specific lockfiles.

    Each language ecosystem should set up a subclass of `LockfileRequest`, like
    `PythonLockfileRequest` and `CoursierLockfileRequest`, and register a union rule. They should
    also set up a simple rule that goes from that class -> `WrappedLockfileRequest`.

    Subclasses will usually want to add additional properties, such as Python interpreter
    constraints.
    """

    resolve_name: str
    lockfile_dest: str


@dataclass(frozen=True)
class WrappedLockfileRequest:
    request: LockfileRequest


@union
class ToolLockfileSentinel:
    """Tools use this as an entry point to say how to generate their tool lockfile.

    Each language ecosystem should set up a union member of `LockfileRequest`, like
    `PythonLockfileRequest`, as explained in that class's docstring.

    Then, each tool should subclass `ToolLockfileSentinel` and set up a rule that goes from the
    subclass -> the language's lockfile request, e.g. BlackLockfileSentinel ->
    PythonLockfileRequest. Register a union rule for the `ToolLockfileSentinel` subclass.
    """

    options_scope: ClassVar[str]
