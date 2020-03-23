# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.reporting.reporting_server import ReportingServerManager
from pants.task.task import QuietTaskMixin, Task

logger = logging.getLogger(__name__)


class ReportingServerKill(QuietTaskMixin, Task):
    """Kill the reporting server."""

    def execute(self):
        server = ReportingServerManager(self.context, self.get_options())

        if not server.is_alive():
            logger.info("No server found.")
            return

        pid = server.pid

        try:
            logger.info(
                "Killing server with {pid} at http://localhost:{port}".format(
                    pid=pid, port=server.socket
                )
            )
            server.terminate()
        except ReportingServerManager.NonResponsiveProcess:
            logger.info("Failed to kill server with pid {pid}!".format(pid=pid))
