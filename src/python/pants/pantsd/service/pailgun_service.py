# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import select
from contextlib import contextmanager

from pants.pantsd.pailgun_server import PailgunServer
from pants.pantsd.service.pants_service import PantsService


class PailgunService(PantsService):
  """A service that runs the Pailgun server."""

  def __init__(self, bind_addr, runner_class, scheduler_service):
    """
    :param tuple bind_addr: The (hostname, port) tuple to bind the Pailgun server to.
    :param class runner_class: The `PantsRunner` class to be used for Pailgun runs.
    :param SchedulerService scheduler_service: The SchedulerService instance for access to the
                                               resident scheduler.
    """
    super(PailgunService, self).__init__()
    self._bind_addr = bind_addr
    self._runner_class = runner_class
    self._scheduler_service = scheduler_service

    self._logger = logging.getLogger(__name__)
    self._pailgun = None

  @property
  def pailgun(self):
    if not self._pailgun:
      self._pailgun = self._setup_pailgun()
    return self._pailgun

  @property
  def pailgun_port(self):
    return self.pailgun.server_port

  def _setup_pailgun(self):
    """Sets up a PailgunServer instance."""
    # Constructs and returns a runnable PantsRunner.
    def runner_factory(sock, arguments, environment):
      return self._runner_class.create(
        sock,
        arguments,
        environment,
        self._scheduler_service
      )

    # Plumb the daemon's lifecycle lock to the `PailgunServer` to safeguard teardown.
    @contextmanager
    def lifecycle_lock():
      with self.lifecycle_lock:
        yield

    return PailgunServer(self._bind_addr, runner_factory, lifecycle_lock)

  def run(self):
    """Main service entrypoint. Called via Thread.start() via PantsDaemon.run()."""
    self._logger.info('starting pailgun server on port {}'.format(self.pailgun_port))

    try:
      # Manually call handle_request() in a loop vs serve_forever() for interruptability.
      while not self.is_killed:
        self.pailgun.handle_request()
    except select.error as e:
      # SocketServer can throw `error: (9, 'Bad file descriptor')` on teardown. Ignore it.
      self._logger.warning('pailgun service shutting down due to an error: {}'.format(e))
    finally:
      self._logger.info('pailgun service on port {} shutting down'.format(self.pailgun_port))

  def terminate(self):
    """Override of PantsService.terminate() that cleans up when the Pailgun server is terminated."""
    # Tear down the Pailgun TCPServer.
    if self.pailgun:
      self.pailgun.server_close()

    super(PailgunService, self).terminate()
