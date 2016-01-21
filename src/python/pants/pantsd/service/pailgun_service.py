# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.pantsd.pailgun_server import PailgunServer
from pants.pantsd.service.pants_service import PantsService


class PailgunService(PantsService):
  """A service that runs the Pailgun server."""

  def __init__(self, bind_addr, exiter_class, runner_class):
    """
    :param tuple bind_addr: The (hostname, port) tuple to bind the Pailgun server to.
    :param class exiter_class: The Exiter class to be used for Pailgun runs.
    :param class runner_class: The PantsRunner class to be used for Pailgun runs.
    """
    super(PailgunService, self).__init__()
    self._logger = logging.getLogger(__name__)
    self._bind_addr = bind_addr
    self._exiter_class = exiter_class
    self._runner_class = runner_class
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
      exiter = self._exiter_class(sock)
      return self._runner_class(sock, exiter, arguments, environment)

    return PailgunServer(self._bind_addr, runner_factory)

  def run(self):
    """Main service entrypoint. Called via Thread.start() via PantsDaemon.run()."""
    self._logger.info('starting pailgun server on port {}'.format(self.pailgun_port))

    # Manually call handle_request() in a loop vs serve_forever() for interruptability.
    while not self.is_killed:
      self.pailgun.handle_request()

  def terminate(self):
    """Override of PantsService.terminate() that cleans up when the Pailgun server is terminated."""
    # Tear down the Pailgun TCPServer.
    if self.pailgun:
      self.pailgun.server_close()

    super(PailgunService, self).terminate()
