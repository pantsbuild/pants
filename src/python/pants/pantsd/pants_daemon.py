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

from pants.base.exiter import Exiter
from pants.goal.run_tracker import RunTracker
from pants.logging.setup import setup_logging
from pants.pantsd.process_manager import ProcessManager


class _LoggerStream(object):
  """A sys.{stdout,stderr} replacement that pipes output to a logger."""

  def __init__(self, logger, log_level, logger_stream):
    """
    :param logging.Logger logger: The logger instance to emit writes to.
    :param int log_level: The log level to use for the given logger.
    :param file logger_stream: The underlying file object the logger is writing to, for
                               determining the fileno to support faulthandler logging.
    """
    self._logger = logger
    self._log_level = log_level
    self._stream = logger_stream

  def write(self, msg):
    for line in msg.rstrip().splitlines():
      self._logger.log(self._log_level, line.rstrip())

  def flush(self):
    return

  def isatty(self):
    return False

  def fileno(self):
    return self._stream.fileno()


class PantsDaemon(ProcessManager):
  """A daemon that manages PantsService instances."""

  JOIN_TIMEOUT_SECONDS = 1
  LOG_NAME = 'pantsd.log'

  class StartupFailure(Exception): pass
  class RuntimeFailure(Exception): pass

  def __init__(self, build_root, work_dir, log_level, native, log_dir=None, services=None,
               metadata_base_dir=None, reset_func=None):
    """
    :param string build_root: The pants build root.
    :param string work_dir: The pants work directory.
    :param string log_level: The log level to use for daemon logging.
    :param string log_dir: The directory to use for file-based logging via the daemon. (Optional)
    :param tuple services: A tuple of PantsService instances to launch/manage. (Optional)
    :param callable reset_func: Called after the daemon is forked to reset
                                any state inherited from the parent process. (Optional)
    """
    super(PantsDaemon, self).__init__(name='pantsd', metadata_base_dir=metadata_base_dir)
    self._logger = logging.getLogger(__name__)
    self._build_root = build_root
    self._work_dir = work_dir
    self._log_level = log_level
    self._native = native
    self._log_dir = log_dir or os.path.join(work_dir, self.name)
    self._services = services or ()
    self._reset_func = reset_func
    self._socket_map = {}
    # N.B. This Event is used as nothing more than a convenient atomic flag - nothing waits on it.
    self._kill_switch = threading.Event()
    self._exiter = Exiter()

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
    result = setup_logging(log_level, log_dir=self._log_dir, log_name=self.LOG_NAME)

    # Close out pre-fork file descriptors.
    self._close_fds()

    # Redirect stdio to the root logger.
    sys.stdout = _LoggerStream(logging.getLogger(), logging.INFO, result.log_stream)
    sys.stderr = _LoggerStream(logging.getLogger(), logging.WARN, result.log_stream)

    self._logger.debug('logging initialized')

    return result.log_stream

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
    log_stream = self._setup_logging(self._log_level)
    self._exiter.set_except_hook(log_stream)
    self._logger.info('pantsd starting, log level is {}'.format(self._log_level))

    # Purge as much state as possible from the pants run that launched us.
    if self._reset_func:
      self._reset_func()

    # Set the process name in ps output to 'pantsd' vs './pants compile src/etc:: -ldebug'.
    set_process_title('pantsd [{}]'.format(self._build_root))

    # Write service socket information to .pids.
    self._write_named_sockets(self._socket_map)

    # Enter the main service runner loop.
    self._setup_services(self._services)
    self._run_services(self._services)

  def pre_fork(self):
    """Pre-fork() callback for ProcessManager.daemonize()."""
    for service in self._services:
      service.pre_fork()

    # Teardown the RunTracker's SubprocPool pre-fork.
    RunTracker.global_instance().shutdown_worker_pool()
    # TODO(kwlzn): This currently aborts tracking of the remainder of the pants run that launched
    # pantsd.

  def post_fork_child(self):
    """Post-fork() child callback for ProcessManager.daemonize()."""
    self._native.set_panic_handler()
    self._run()
