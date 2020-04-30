# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import time
from typing import Iterator


def attempts(
    msg: str, delay: float = 0.5, timeout: float = 30, backoff: float = 1.2,
) -> Iterator[None]:
    """A generator that yields a number of times before failing.

    A caller should break out of a loop on the generator in order to succeed.
    """
    count = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        count += 1
        yield
        time.sleep(delay)
        delay *= backoff
    raise AssertionError(f"After {count} attempts in {timeout} seconds: {msg}")
