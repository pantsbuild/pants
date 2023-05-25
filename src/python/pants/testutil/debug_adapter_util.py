# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os


def debugadapter_port_for_testing() -> int:
    """Return a unique-per-concurrent-process debug adapter port.

    Use this in Pants's (and plugins') own tests to avoid collisions.

    Assumes that the env var TEST_EXECUTION_SLOT has been set. If not, all tests
    will use the same port, and collisions may occur.
    """
    execution_slot = os.environ.get("TEST_EXECUTION_SLOT", "0")
    return 22000 + int(execution_slot)
