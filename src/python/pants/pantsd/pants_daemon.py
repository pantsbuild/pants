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

from pants.goal.run_tracker import RunTracker
from pants.logging.setup import setup_logging
from pants.pantsd.process_manager import ProcessManager
from pants.pantsd.util import clean_global_runtime_state


class _StreamLogger(object):
  """A sys.{stdout,stderr} replacement that pipes output to a logger."""

  def __init__(self, logger, log_level):
    """
    :param logging.Logger logger: The logger instance to emit writes to.
    :param int log_level: The log level to use for the given logger.
    """
    self._logger = logger
    self._log_level = log_level

  def write(self, msg):
    for line in msg.rstrip().splitlines():
      self._logger.log(self._log_level, line.rstrip())

  def flush(self):
    return


class PantsDaemon(ProcessManager):
  """A daemon that manages PantsService instances."""

  JOIN_TIMEOUT_SECONDS = 1
  LOG_NAME = 'pantsd.log'

  class StartupFailure(Exception): pass
  class RuntimeFailure(Exception): pass

  def __init__(self, build_root, work_dir, log_level, log_dir=None, services=None,
               metadata_base_dir=None):
    """
    :param string build_root: The pants build root.
    :param string work_dir: The pants work directory.
    :param int log_level: The log level to use for daemon logging.
    :param string log_dir: The directory to use for file-based logging via the daemon. (Optional)
    :param tuple services: A tuple of PantsService instances to launch/manage. (Optional)
    """
    super(PantsDaemon, self).__init__(name='pantsd', metadata_base_dir=metadata_base_dir)
    self._logger = logging.getLogger(__name__)
    self._build_root = build_root
    self._work_dir = work_dir
    self._log_level = log_level
    self._log_dir = log_dir or os.path.join(work_dir, self.name)
    self._services = services or ()
    self._socket_map = {}
    # N.B. This Event is used as nothing more than a convenient atomic flag - nothing waits on it.
    self._kill_switch = threading.Event()

  @property
  def is_killed(self):
    return self._kill_switch.is_set()

  def set_services(self, services):
    self._services = services

  def set_socket_map(self, socket_map):
    self._socket_map = socket_map

  def shutdown(self, service_thread_map):
    """Gracefully terminate all services and kill the main PantsDaemon loop."""
    for service, service_thread in service_thread_map.items():
      self._logger.info('terminating pantsd service: {}'.format(service))
      service.terminate()
      service_thread.join()
    self._logger.info('terminating pantsd')
    self._kill_switch.set()

  @staticmethod
  def _close_fds():
    """Close pre-fork stdio streams to avoid output in the pants process that launched pantsd."""
    for fd in (sys.stdin, sys.stdout, sys.stderr):
      file_no = fd.fileno()
      fd.flush()
      fd.close()
      os.close(file_no)

  def _setup_logging(self, log_level):
    """Reinitialize logging post-fork to clear all handlers, file descriptors, locks etc.

    This must happen first thing post-fork, before any further logging is emitted.
    """
    # Re-initialize the childs logging locks post-fork to avoid potential deadlocks if pre-fork
    # threads have any locks acquired at the time of fork.
    logging._lock = threading.RLock() if logging.thread else None
    for handler in logging.getLogger().handlers:
      handler.createLock()

    # Invoke a global teardown for all logging handlers created before now.
    logging.shutdown()

    # Reinitialize logging for the daemon context.
    setup_logging(log_level, console_stream=None, log_dir=self._log_dir, log_name=self.LOG_NAME)

    # Close out pre-fork file descriptors.
    self._close_fds()

    # Redirect stdio to the root logger.
    sys.stdout = _StreamLogger(logging.getLogger(), logging.INFO)
    sys.stderr = _StreamLogger(logging.getLogger(), logging.WARN)

    self._logger.debug('logging initialized')

  def _setup_services(self, services):
    for service in services:
      self._logger.info('setting up service {}'.format(service))
      service.setup()

  def _run_services(self, services):
    """Service runner main loop."""
    if not services:
      self._logger.critical('no services to run, bailing!')
      return

    service_thread_map = {service: threading.Thread(target=service.run) for service in services}

    # Start services.
    for service, service_thread in service_thread_map.items():
      self._logger.info('starting service {}'.format(service))
      try:
        service_thread.start()
      except (RuntimeError, service.ServiceError):
        self.shutdown(service_thread_map)
        raise self.StartupFailure('service {} failed to start, shutting down!'.format(service))

    # Monitor services.
    while not self.is_killed:
      for service, service_thread in service_thread_map.items():
        if not service_thread.is_alive():
          self.shutdown(service_thread_map)
          raise self.RuntimeFailure('service failure for {}, shutting down!'.format(service))
        else:
          # Avoid excessive CPU utilization.
          service_thread.join(self.JOIN_TIMEOUT_SECONDS)

  def _write_named_sockets(self, socket_map):
    """Write multiple named sockets using a socket mapping."""
    for socket_name, socket_info in socket_map.items():
      self.write_named_socket(socket_name, socket_info)

  def _run(self):
    """Synchronously run pantsd."""
    # Switch log output to the daemon's log stream from here forward.
    self._setup_logging(self._log_level)
    self._logger.info('pantsd starting, log level is {}'.format(self._log_level))

    # Purge as much state as possible from the pants run that launched us.
    clean_global_runtime_state()

    # Set the process name in ps output to 'pantsd' vs './pants compile src/etc:: -ldebug'.
    set_process_title('pantsd [{}]'.format(self._build_root))

    # Write service socket information to .pids.
    self._write_named_sockets(self._socket_map)

    # Enter the main service runner loop.
    self._setup_services(self._services)
    self._run_services(self._services)

  def pre_fork(self):
    """Pre-fork() callback for ProcessManager.daemonize()."""
    # Teardown the RunTracker's SubprocPool pre-fork.
    RunTracker.global_instance().shutdown_worker_pool()
    # TODO(kwlzn): This currently aborts tracking of the remainder of the pants run that launched
    # pantsd.

  def post_fork_child(self):
    """Post-fork() child callback for ProcessManager.daemonize()."""
    self._run()
