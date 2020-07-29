# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class Return:
    """Indicates that a Node successfully returned a value."""

    value: Any


@dataclass(frozen=True)
class Throw:
    """Indicates that a Node should have been able to return a value, but failed."""

    exc: Exception
    python_traceback: Optional[str] = None
    engine_traceback: Tuple[str, ...] = ()
