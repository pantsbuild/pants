# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import time

from pants.engine.internals.native import RawFdRunner
from pants.pantsd.service.pants_service import PantsService
from pants.pantsd.service.scheduler_service import SchedulerService

logger = logging.getLogger(__name__)


class PailgunService(PantsService):
    """A service that runs the Pailgun server."""

    def __init__(
        self, port_requested: int, runner: RawFdRunner, scheduler_service: SchedulerService,
    ):
        """
        :param port_requested: A port to bind the service to, or 0 to choose a random port (which
          will be exposed by `pailgun_port`).
        :param runner: A runner for inbound requests. Generally this will be a method of
          `DaemonPantsRunner`.
        :param scheduler_service: The SchedulerService instance for access to the resident scheduler.
        """
        super().__init__()

        self._scheduler = scheduler_service._scheduler
        self._server = self._setup_server(port_requested, runner)

    def _setup_server(self, port_requested, runner):
        return self._scheduler.new_nailgun_server(port_requested, runner)

    def pailgun_port(self):
        return self._scheduler.nailgun_server_await_bound(self._server)

    def run(self):
        """Main service entrypoint.

        Called via Thread.start() via PantsDaemon.run().
        """
        try:
            logger.info("started pailgun server on port {}".format(self.pailgun_port()))
            while not self._state.is_terminating:
                # Once the server has started, `await_bound` will return quickly with an error if it
                # has exited.
                self.pailgun_port()
                time.sleep(0.5)
        except BaseException:
            logger.error("pailgun service shutting down due to an error", exc_info=True)
            self.terminate()
        finally:
            logger.info("pailgun service on shutting down")

    def terminate(self):
        """Override of PantsService.terminate() that drops the server when terminated."""
        self._server = None
        super().terminate()
