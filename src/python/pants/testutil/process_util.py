# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Callable

from pants.engine.process import Process


def process_assertion(**assertions) -> Callable[[Process], None]:
    def assert_process(process: Process) -> None:
        for attr, expected in assertions.items():
            assert getattr(process, attr) == expected

    return assert_process
