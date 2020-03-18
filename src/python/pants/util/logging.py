# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from enum import Enum

# A custom log level for pants trace logging.
TRACE = 5


# Although logging supports the WARN level, its not documented and could conceivably be yanked.
# Since pants has supported 'warn' since inception, leave the 'warn' choice as-is but explicitly
# setup a 'WARN' logging level name that maps to 'WARNING'.
logging.addLevelName(logging.WARNING, "WARN")
logging.addLevelName(TRACE, "TRACE")


class LogLevel(Enum):
    TRACE = ("trace", TRACE)
    DEBUG = ("debug", logging.DEBUG)
    INFO = ("info", logging.INFO)
    WARN = ("warn", logging.WARN)
    ERROR = ("error", logging.ERROR)

    _level: int

    def __new__(cls, value: str, level: int) -> "LogLevel":
        member: "LogLevel" = object.__new__(cls)
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
