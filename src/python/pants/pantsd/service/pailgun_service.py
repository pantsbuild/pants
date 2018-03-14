# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import select
import sys
import traceback
from contextlib import contextmanager

from pants.init.options_initializer import OptionsInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pailgun_server import PailgunServer
from pants.pantsd.service.pants_service import PantsService


class PailgunService(PantsService):
  """A service that runs the Pailgun server."""

  def __init__(self, bind_addr, exiter_class, runner_class, target_roots_calculator, scheduler_service):
    """
    :param tuple bind_addr: The (hostname, port) tuple to bind the Pailgun server to.
    :param class exiter_class: The `Exiter` class to be used for Pailgun runs.
    :param class runner_class: The `PantsRunner` class to be used for Pailgun runs.
    :param class target_roots_calculator: The `TargetRootsCalculator` class to be used for target
      root parsing.
    :param SchedulerService scheduler_service: The SchedulerService instance for access to the
                                               resident scheduler.
    """
    super(PailgunService, self).__init__()
    self._bind_addr = bind_addr
    self._exiter_class = exiter_class
    self._runner_class = runner_class
    self._target_roots_calculator = target_roots_calculator
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
      exiter = self._exiter_class(sock)
      graph_helper = None
      deferred_exc = None

      # Capture the size of the graph prior to any warming, for stats.
      preceding_graph_size = self._scheduler_service.product_graph_len()
      self._logger.debug('resident graph size: %s', preceding_graph_size)

      self._logger.debug('execution commandline: %s', arguments)
      options, _ = OptionsInitializer(OptionsBootstrapper(args=arguments)).setup(init_logging=False)
      target_roots = self._target_roots_calculator.create(
        options,
        change_calculator=self._scheduler_service.change_calculator
      )

      try:
        self._logger.debug('warming the product graph via %s', self._scheduler_service)
        # N.B. This call is made in the pre-fork daemon context for reach and reuse of the
        # resident scheduler.
        graph_helper = self._scheduler_service.warm_product_graph(target_roots)
      except Exception:
        deferred_exc = sys.exc_info()
        self._logger.warning(
          'encountered exception during SchedulerService.warm_product_graph(), deferring:\n%s',
          ''.join(traceback.format_exception(*deferred_exc))
        )

      return self._runner_class(
        sock,
        exiter,
        arguments,
        environment,
        target_roots,
        graph_helper,
        self.fork_lock,
        preceding_graph_size,
        deferred_exc
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
    except select.error:
      # SocketServer can throw `error: (9, 'Bad file descriptor')` on teardown. Ignore it.
      self._logger.warning('pailgun service shutting down')

  def terminate(self):
    """Override of PantsService.terminate() that cleans up when the Pailgun server is terminated."""
    # Tear down the Pailgun TCPServer.
    if self.pailgun:
      self.pailgun.server_close()

    super(PailgunService, self).terminate()
