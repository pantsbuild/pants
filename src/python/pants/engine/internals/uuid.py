# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional, cast

from pants.engine.rules import collect_rules, rule
from pants.util.meta import frozen_after_init


class UUIDScope(Enum):
    PER_CALL = "call"
    PER_SESSION = "session"


@frozen_after_init
@dataclass(unsafe_hash=True)
class UUIDRequest:
    scope: str

    def __init__(self, scope: Optional[str] = None) -> None:
        self.scope = scope if scope is not None else self._to_scope_name(UUIDScope.PER_CALL)

    @staticmethod
    def _to_scope_name(scope: UUIDScope) -> str:
        if scope == UUIDScope.PER_CALL:
            return uuid.uuid4().hex
        return cast(str, scope.value)

    @classmethod
    def scoped(cls, scope: UUIDScope) -> "UUIDRequest":
        return cls(cls._to_scope_name(scope))


@rule
async def generate_uuid(_: UUIDRequest) -> uuid.UUID:
    """A rule to generate a UUID.

    Useful primarily to force a rule to re-run: a rule that `await Get`s on a UUIDRequest will be
    uncacheable, because this rule is itself uncacheable.

    Note that this will return a new UUID each time if requested multiple times in a single session.
    If you want two requests to return the same UUID, set the `scope` field in both requests to some
    fixed scope value.
    """
    return uuid.uuid4()


def rules():
    return collect_rules()
