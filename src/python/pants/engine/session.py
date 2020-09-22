# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Type

from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass
class SessionValues:
    """Values set for the Session, and exposed to @rules."""

    values: FrozenDict[Type, Any]

    def __init__(self, values: Optional[Mapping[Type, Any]] = None) -> None:
        self.values = FrozenDict(values or {})
