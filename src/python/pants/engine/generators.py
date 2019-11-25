# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Generator, Generic, Iterator, TypeVar

logger = logging.getLogger(__name__)


_Output = TypeVar("_Output")


@dataclass(frozen=True)
class Retry(Generic[_Output]):
    awaitable: Awaitable[_Output]
    num_tries: int = 1

    class WrappedError(Exception):
        def __init__(self, num_tries: int, message: str) -> None:
            super().__init__(f"failed after {num_tries} tries: {message}")
            self.num_tries = num_tries

    def __await__(self) -> Iterator[_Output]:
        last_failure = None
        for i in range(0, self.num_tries):
            try:
                logger.debug(f"iteration {i} for awaitable {self.awaitable}")
                x = yield from self.awaitable.__await__()
                logger.debug(f"successful: {x}")
                return x
            except Exception as e:
                last_failure = e

        raise self.WrappedError(self.num_tries, str(last_failure)) from last_failure
