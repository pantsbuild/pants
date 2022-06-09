# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from enum import Enum
from functools import total_ordering

# A custom log level for pants trace logging.
TRACE = 5


@total_ordering
class LogLevel(Enum):
    """Exposes an enum of the Python `logging` module's levels, with the addition of TRACE.

    NB: The `logging` module uses the opposite integer ordering of levels from Rust's `log` crate,
    but the ordering implementation of this enum inverts its comparison to make its ordering align
    with Rust's.
    """

    TRACE = ("trace", TRACE)
    DEBUG = ("debug", logging.DEBUG)
    INFO = ("info", logging.INFO)
    WARN = ("warn", logging.WARN)
    ERROR = ("error", logging.ERROR)

    _level: int

    def __new__(cls, value: str, level: int) -> LogLevel:
        member: LogLevel = object.__new__(cls)
        member._value_ = value
        member._level = level
        return member

    @property
    def level(self) -> int:
        return self._level

    def log(self, logger: logging.Logger, *args, **kwargs) -> None:
        logger.log(self._level, *args, **kwargs)

    def set_level_for(self, logger: logging.Logger):
        logger.setLevel(self.level)

    def __lt__(self, other):
        if not isinstance(other, LogLevel):
            return NotImplemented
        return self._level > other._level
