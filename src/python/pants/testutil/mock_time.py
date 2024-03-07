# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


class MockTime:
    """A mock implementation of time.time and time.sleep.

    Use to test code that interacts with the clock without relying on real clock behavior.
    """

    def __init__(self) -> None:
        self._now: float = 0.0

    def time(self) -> float:
        return self._now

    def sleep(self, interval: float) -> None:
        self._now += interval
