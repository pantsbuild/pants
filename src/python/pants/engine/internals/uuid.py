# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import random
import uuid
from dataclasses import dataclass, field

from pants.engine.rules import RootRule, _uncacheable_rule


@dataclass(frozen=True)
class UUIDRequest:
    randomizer: float = field(default_factory=random.random)


@_uncacheable_rule
async def generate_uuid(_: UUIDRequest) -> uuid.UUID:
    """A rule to generate a UUID.

    Useful primarily to force a rule to re-run: a rule that `await Get`s on a UUIDRequest will be
    uncacheable, because this rule is itself uncacheable.

    Note that this will return a new UUID each time if request multiple times in a single session.
    If you want two requests to return the same UUID, set the `randomizer` field in both
    requests to some fixed value.
    """
    return uuid.uuid4()


def rules():
    return [generate_uuid, RootRule(UUIDRequest)]
