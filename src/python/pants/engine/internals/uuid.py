# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import uuid
from dataclasses import dataclass

from pants.engine.rules import RootRule, uncacheable_rule


@dataclass(frozen=True)
class UUIDRequest:
    pass


@uncacheable_rule
async def generate_uuid(_: UUIDRequest) -> uuid.UUID:
    """A rule to generate a UUID.

    Useful primarily to force a rule to re-run: a rule that `await Get`s on a UUIDRequest will be
    uncacheable, because this rule is itself uncacheable.
    """
    return uuid.uuid4()


def rules():
    return [generate_uuid, RootRule(UUIDRequest)]
