# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.base.exceptions import TaskError
from pants.reporting.reporting_server import ReportingServerManager
from pants.task.task import QuietTaskMixin, Task
from pants.util import desktop


logger = logging.getLogger(__name__)


class ReportingServerRun(QuietTaskMixin, Task):
  """Run the reporting server."""

  @classmethod
  def register_options(cls, register):
    super(ReportingServerRun, cls).register_options(register)
    register('--port', type=int, default=0,
             help='Serve on this port. Leave unset to choose a free port '
                  'automatically (recommended if using pants concurrently in '
                  'multiple workspaces on the same host).')
    register('--allowed-clients', type=list, default=['127.0.0.1'],
             help='Only requests from these IPs may access this server. Useful for '
                  'temporarily showing build results to a colleague. The special '
                  'value ALL means any client may connect. Use with caution, as '
                  'your source code is exposed to all allowed clients!')
    register('--open', type=bool,
             help='Attempt to open the server web ui in a browser.')
    register('--template-dir', advanced=True,
             help='Use templates from this dir instead of the defaults.')
    register('--assets-dir', advanced=True,
             help='Use assets from this dir instead of the defaults.')

  def _maybe_open(self, port):
    if self.get_options().open:
      try:
        desktop.ui_open('http://localhost:{port}'.format(port=port))
      except desktop.OpenError as e:
        raise TaskError(e)

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
      logger.info('To kill, run `./pants killserver`')

    self._maybe_open(manager.socket)
