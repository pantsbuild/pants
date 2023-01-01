# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.internals.scheduler import Scheduler


@dataclass(frozen=True)
class BootstrapScheduler:
    """A Scheduler that has been configured with only the rules for bootstrapping."""

    scheduler: Scheduler
