# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.backend.core.tasks.task import QuietTaskMixin, Task
from pants.binaries import binary_util
from pants.reporting.reporting_server import ReportingServerManager


logger = logging.getLogger(__name__)


class RunServer(QuietTaskMixin, Task):
  """Runs the reporting server."""

  @classmethod
  def register_options(cls, register):
    super(RunServer, cls).register_options(register)
    register('--port', type=int, default=0,
             help='Serve on this port. Leave unset to choose a free port '
                  'automatically (recommended if using pants concurrently in '
                  'multiple workspaces on the same host).')
    register('--allowed-clients', action='append', default=['127.0.0.1'],
             help='Only requests from these IPs may access this server. Useful for '
                  'temporarily showing build results to a colleague. The special '
                  'value ALL means any client may connect. Use with caution, as '
                  'your source code is exposed to all allowed clients!')
    register('--open', action='store_true', default=False,
             help='Attempt to open the server web ui in a browser.')
    register('--template-dir', advanced=True,
             help='Use templates from this dir instead of the defaults.')
    register('--assets-dir', advanced=True,
             help='Use assets from this dir instead of the defaults.')

  def _maybe_open(self, port):
    if self.get_options().open:
      binary_util.ui_open('http://localhost:{port}'.format(port=port))

  def execute(self):
    manager = ReportingServerManager(self.context, self.get_options())

    if manager.is_alive():
      logger.info('Server already running with pid {pid} at http://localhost:{port}'
                  .format(pid=manager.pid, port=manager.socket))
    else:
      manager.daemonize()
      manager.await_socket(10)

      logger.info('Launched server with pid {pid} at http://localhost:{port}'
                  .format(pid=manager.pid, port=manager.socket))

    self._maybe_open(manager.socket)


class KillServer(QuietTaskMixin, Task):
  """Kills the reporting server."""

  def execute(self):
    server = ReportingServerManager(self.context, self.get_options())

    if not server.is_alive():
      logger.info('No server found.')
      return

    pid = server.pid

    try:
      logger.info('Killing server with {pid} at http://localhost:{port}'
                  .format(pid=pid, port=server.socket))
      server.terminate()
    except ReportingServerManager.NonResponsiveProcess:
      logger.info('Failed to kill server with pid {pid}!'.format(pid=pid))
