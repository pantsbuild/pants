# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os

from pants.option.option_types import IntOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class DebugAdapterSubsystem(Subsystem):
    options_scope = "debug-adapter"
    help = softwrap(
        """
        Options used to configure and launch a Debug Adapter server.

        See https://microsoft.github.io/debug-adapter-protocol/ for more information.
        """
    )

    host = StrOption(default="127.0.0.1", help="The hostname to use when launching the server.")
    port = IntOption(
        default=5678,
        help="The port to use when launching the server.",
    )

    @staticmethod
    def port_for_testing() -> int:
        """Return a custom port we can use in Pants's own tests to avoid collisions.

        Assumes that the env var TEST_EXECUTION_SLOT has been set. If not, all tests will use the
        same port, and collisions may occur.
        """
        execution_slot = os.environ.get("TEST_EXECUTION_SLOT", "0")
        return 22000 + int(execution_slot)
