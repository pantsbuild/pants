# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.option.options import Options
from pants.pantsd import pants_daemon
from pants.pantsd.process_manager import PantsDaemonProcessManager

logger = logging.getLogger(__name__)


class PantsDaemonClient(PantsDaemonProcessManager):
    """A client for interacting with a "potentially running" pantsd instance."""

    @dataclass(frozen=True)
    class Handle:
        """A handle to a "probably running" pantsd instance.

        We attempt to verify that the pantsd instance is still running when we create a Handle, but
        after it has been created it is entirely possible that the pantsd instance perishes.
        """

        pid: int
        port: int
        metadata_base_dir: str

    def __init__(self, bootstrap_options: Options):
        super().__init__(bootstrap_options, daemon_entrypoint=pants_daemon.__name__)

    def maybe_launch(self) -> PantsDaemonClient.Handle:
        """Creates and launches a daemon instance if one does not already exist."""
        with self.lifecycle_lock:
            if self.needs_restart(self.options_fingerprint):
                return self._launch()
            else:
                # We're already launched.
                return PantsDaemonClient.Handle(
                    pid=self.await_pid(10),
                    port=self.await_socket(10),
                    metadata_base_dir=self._metadata_base_dir,
                )

    def restart(self) -> PantsDaemonClient.Handle:
        """Restarts a running daemon instance."""
        with self.lifecycle_lock:
            # N.B. This will call `pantsd.terminate()` before starting.
            return self._launch()

    def _launch(self) -> PantsDaemonClient.Handle:
        """Launches pantsd in a subprocess.

        N.B. This should always be called under care of the `lifecycle_lock`.
        """
        self.terminate()
        logger.debug("Launching pantsd")
        self.daemon_spawn()
        # Wait up to 60 seconds each for pantsd to write its pidfile and open its socket.
        pantsd_pid = self.await_pid(60)
        listening_port = self.await_socket(60)
        logger.debug(f"pantsd is running at pid {self.pid}, pailgun port is {listening_port}")
        return self.Handle(pantsd_pid, listening_port, self._metadata_base_dir)
