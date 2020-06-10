# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.init.engine_initializer import LegacyGraphScheduler
from pants.pantsd.service.pants_service import PantsServices


class PantsDaemonCore:
    """A container for the mutable state of a PantsDaemon.

    This class also serves to avoid a reference cycle between DaemonPantsRunner and PantsDaemon,
    which both have a reference to the core, and use it to get access to the Scheduler and current
    PantsServices.
    """

    def __init__(
        self, scheduler: LegacyGraphScheduler, services: PantsServices,
    ):
        self._scheduler = scheduler
        self._services = services

    def prepare_scheduler(self) -> LegacyGraphScheduler:
        return self._scheduler
