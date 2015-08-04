# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import sys
import threading

from setproctitle import setproctitle as set_process_title

from pants.base.build_environment import get_buildroot
from pants.logging.setup import setup_logging
from pants.pantsd.process_manager import ProcessManager
from pants.pantsd.service.build_graph_service import BuildGraphService
from pants.pantsd.service.fs_event_service import FSEventService
from pants.pantsd.service.http_service import HttpService


class StreamLogger(object):
  def __init__(self, logger, log_level=logging.INFO):
    self._logger = logger
    self._log_level = log_level

  def write(self, msg):
    [self._logger.log(self._log_level, line.rstrip()) for line in msg.rstrip().splitlines()]


class PantsDaemon(ProcessManager):
  SERVICES = [HttpService, BuildGraphService, FSEventService]
  JOIN_TIMEOUT = 1

  def __init__(self, options):
    ProcessManager.__init__(self, name='pantsd')
    self.options = options
    self._logger = logging.getLogger(__name__)
    self._log_dir = options.log_dir or os.path.join(get_buildroot(), '.pants.d', self.name)

    self._services = {}

  def _reset_logging_locks(self):
    """Re-initialize the childs logging module & Handler level lock post-fork to avoid deadlocks."""
    logging._lock = threading.RLock()
    for handler in self._logger.handlers:
      handler.lock = threading.RLock()

  def _setup_logging(self, log_level):
    """Reinitialize logging post-fork to clear all handlers, file descriptors, locks etc.

       This must happen first thing post-fork, before any further logging is emitted.
    """
    self._reset_logging_locks()
    setup_logging(log_level, console_stream=False, log_dir=self._log_dir, log_name='pantsd.log')

    self._logger = logging.getLogger(__name__)
    # Redirect stdout/stderr (e.g. for Thread exceptions) to the logger.
    sys.stdout = sys.stderr = StreamLogger(self._logger)
    self._logger.debug('logging initialized')

  def _run_services(self, services):
    """Run the main pants services in a continuous loop."""
    if not services:
      self._logger.critical('no services to run, bailing!')
      return

    service_map = {service_class.__name__: service_class for service_class in self.SERVICES}

    # TODO: service flap detection.
    while 1:
      for service_name, service_class in service_map.items():
        # Rely on the Singleton mechanics of PantsService to reach or init a service via its class.
        service = service_class(pantsd=self, options=self.options)
        if not service.is_alive():
          try:
            service.start()
            self._logger.info('started service {}'.format(service_name))
          except RuntimeError:
            self._logger.info('service {} is dead, restarting!'.format(service_name))
            # Can't restart a dead thread. Kill the instance and loop to re-construct.
            service._destroy_singleton()
          else:
            # Avoid excessive CPU utilization.
            service.join(self.JOIN_TIMEOUT)

  def run(self, log_level):
    """Synchronously run the pants daemon."""
    # Switch to writing to pantsd.log from here on out.
    self._setup_logging(log_level)
    self._logger.info('pantsd starting')

    # Set the process name in ps to 'pantsd' vs './pants compile src/etc:: -ldebug'.
    set_process_title('pantsd')

    # Enter the service runner loop.
    self._run_services(self.SERVICES)

  def post_fork_child(self, log_level):
    """Post-fork() child callback for ProcessManager.daemonize()."""
    self.run(log_level)
