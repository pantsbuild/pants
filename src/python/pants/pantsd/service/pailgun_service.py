# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from contextlib import contextmanager

from pants.pantsd.pailgun_server import PailgunServer
from pants.pantsd.service.pants_service import PantsService


class PailgunService(PantsService):
    """A service that runs the Pailgun server."""

    def __init__(self, bind_addr, runner_class, scheduler_service, shutdown_after_run):
        """
        :param tuple bind_addr: The (hostname, port) tuple to bind the Pailgun server to.
        :param class runner_class: The `PantsRunner` class to be used for Pailgun runs. Generally this
          will be `DaemonPantsRunner`, but this decoupling avoids a cycle between the `pants.pantsd` and
          `pants.bin` packages.
        :param SchedulerService scheduler_service: The SchedulerService instance for access to the
                                                   resident scheduler.
        :param bool shutdown_after_run: PailgunService should shut down after running the first request.
        """
        super().__init__()
        self._bind_addr = bind_addr
        self._runner_class = runner_class
        self._scheduler_service = scheduler_service

        self._logger = logging.getLogger(__name__)
        self._pailgun = None
        self._shutdown_after_run = shutdown_after_run if shutdown_after_run else False

    @property
    def pailgun(self):
        if not self._pailgun:
            self._pailgun = self._setup_pailgun()
        return self._pailgun

    @property
    def pailgun_port(self):
        return self.pailgun.server_port

    def _request_complete_callback(self):
        if self._shutdown_after_run:
            self.terminate()

    def _setup_pailgun(self):
        """Sets up a PailgunServer instance."""
        # Constructs and returns a runnable PantsRunner.
        def runner_factory(sock, arguments, environment):
            return self._runner_class.create(sock, arguments, environment, self._scheduler_service,)

        # Plumb the daemon's lifecycle lock to the `PailgunServer` to safeguard teardown.
        # This indirection exists to allow the server to be created before PantsService.setup
        # has been called to actually initialize the `services` field.
        @contextmanager
        def lifecycle_lock():
            with self.services.lifecycle_lock:
                yield

        return PailgunServer(
            self._bind_addr, runner_factory, lifecycle_lock, self._request_complete_callback
        )

    def run(self):
        """Main service entrypoint.

        Called via Thread.start() via PantsDaemon.run().
        """
        self._logger.info("starting pailgun server on port {}".format(self.pailgun_port))

        try:
            # Manually call handle_request() in a loop vs serve_forever() for interruptability.
            while not self._state.is_terminating:
                self.pailgun.handle_request()
                self._state.maybe_pause()
        except Exception:
            self._logger.error("pailgun service shutting down due to an error", exc_info=True)
        finally:
            self._logger.info("pailgun service on port {} shutting down".format(self.pailgun_port))

    def terminate(self):
        """Override of PantsService.terminate() that cleans up when the Pailgun server is
        terminated."""
        # Tear down the Pailgun TCPServer.
        if self.pailgun:
            self.pailgun.server_close()

        super().terminate()
