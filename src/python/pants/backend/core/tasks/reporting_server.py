# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import multiprocessing
import os
import re
import signal
import socket
import sys

from pants import binary_util
from pants.backend.core.tasks.task import QuietTaskMixin, Task
from pants.base.build_environment import get_buildroot
from pants.reporting.reporting_server import ReportingServer, ReportingServerManager


class RunServer(Task, QuietTaskMixin):
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

  def execute(self):
    DONE = '__done_reporting'

    def maybe_open(port):
      if self.get_options().open:
        binary_util.ui_open('http://localhost:{port}'.format(port=port))

    (pid, port) = ReportingServerManager.get_current_server_pid_and_port()
    if port:
      maybe_open(port)
      print('Server already running with pid {pid} at http://localhost:{port}'
            .format(port=port, pid=pid), file=sys.stderr)
      return

    def run_server(reporting_queue):
      def report_launch(actual_port):
        reporting_queue.put(
          'Launching server with pid {pid} at http://localhost:{port}'
          .format(pid=os.getpid(), port=actual_port))

      def done_reporting():
        reporting_queue.put(DONE)

      try:
        # We mustn't block in the child, because the multiprocessing module enforces that the
        # parent either kills or joins to it. Instead we fork a grandchild that inherits the queue
        # but is allowed to block indefinitely on the server loop.
        if not os.fork():
          # Child process.
          # The server finds run-specific info dirs by looking at the subdirectories of info_dir,
          # which is conveniently and obviously the parent dir of the current run's info dir.
          info_dir = os.path.dirname(self.context.run_tracker.run_info_dir)
          # If these are specified explicitly in the config, use those. Otherwise
          # they will be None, and we'll use the ones baked into this package.
          template_dir = self.get_options().template_dir
          assets_dir = self.get_options().assets_dir
          settings = ReportingServer.Settings(info_dir=info_dir, template_dir=template_dir,
                                              assets_dir=assets_dir, root=get_buildroot(),
                                              allowed_clients=self.get_options().allowed_clients)
          server = ReportingServer(self.get_options().port, settings)
          actual_port = server.server_port()
          ReportingServerManager.save_current_server_port(actual_port)
          report_launch(actual_port)
          done_reporting()
          # Block forever here.
          server.start()
      except socket.error:
        done_reporting()
        raise

    # We do reporting on behalf of the child process (necessary, since reporting may be buffered in
    # a background thread). We use multiprocessing.Process() to spawn the child so we can use that
    # module's inter-process Queue implementation.
    reporting_queue = multiprocessing.Queue()
    proc = multiprocessing.Process(target=run_server, args=[reporting_queue])
    proc.daemon = True
    proc.start()
    s = reporting_queue.get()
    while s != DONE:
      print(s, file=sys.stderr)
      s = reporting_queue.get()
    # The child process is done reporting, and is now in the server loop, so we can proceed.
    (_, server_port) = ReportingServerManager.get_current_server_pid_and_port()
    maybe_open(server_port)


class KillServer(Task, QuietTaskMixin):
  """Kills the reporting server."""

  pidfile_re = re.compile(r'port_(\d+)\.pid')

  def execute(self):
    info = ReportingServerManager.get_current_server_info()
    if not info:
      print('No server found.', file=sys.stderr)
    # There should only be one pidfile, but in case there are many, we kill them all here.
    for pidfile, pid, port in info:
      with open(pidfile, 'r') as infile:
        pidstr = infile.read()
      try:
        os.unlink(pidfile)
        pid = int(pidstr)
        os.kill(pid, signal.SIGKILL)
        print('Killed server with {pid} at http://localhost:{port}'.format(pid=pid, port=port),
              file=sys.stderr)
      except (ValueError, OSError):
        pass
