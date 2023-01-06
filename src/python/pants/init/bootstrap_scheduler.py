# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.internals.scheduler import Scheduler


@dataclass(frozen=True)
class BootstrapScheduler:
    """A Scheduler that has been configured with only the rules for bootstrapping."""

    scheduler: Scheduler


@dataclass(frozen=True)
class BootstrapStatus:
    """A singleton value that `@rules` can use to determine whether bootstrap is underway.

    Bootstrap runs occur before plugins are loaded, and so when they parse BUILD files, they may
    need to ignore unrecognized symbols (which might be provided by plugins which are loaded later).
    """

    in_progress: bool
