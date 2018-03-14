# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import sys
import threading
from contextlib import contextmanager

from setproctitle import setproctitle as set_process_title

from pants.base.build_environment import get_buildroot
from pants.base.exiter import Exiter
from pants.bin.daemon_pants_runner import DaemonExiter, DaemonPantsRunner
from pants.bin.engine_initializer import EngineInitializer
from pants.engine.native import Native
from pants.init.target_roots_calculator import TargetRootsCalculator
from pants.logging.setup import setup_logging
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.options_fingerprinter import OptionsFingerprinter
from pants.pantsd.process_manager import FingerprintedProcessManager
from pants.pantsd.service.fs_event_service import FSEventService
from pants.pantsd.service.pailgun_service import PailgunService
from pants.pantsd.service.scheduler_service import SchedulerService
from pants.pantsd.service.store_gc_service import StoreGCService
from pants.pantsd.watchman_launcher import WatchmanLauncher
from pants.util.collections import combined_dict
from pants.util.contextutil import stdio_as
from pants.util.memo import memoized_property


class _LoggerStream(object):
  """A sys.{stdout,stderr} replacement that pipes output to a logger."""

  def __init__(self, logger, log_level, handler):
    """
    :param logging.Logger logger: The logger instance to emit writes to.
    :param int log_level: The log level to use for the given logger.
    :param Handler handler: The underlying log handler, for determining the fileno
                            to support faulthandler logging.
    """
    self._logger = logger
    self._log_level = log_level
    self._handler = handler

  def write(self, msg):
    for line in msg.rstrip().splitlines():
      self._logger.log(self._log_level, line.rstrip())

  def flush(self):
    return

  def isatty(self):
    return False

  def fileno(self):
    return self._handler.stream.fileno()


class PantsDaemon(FingerprintedProcessManager):
  """A daemon that manages PantsService instances."""

  JOIN_TIMEOUT_SECONDS = 1
  LOG_NAME = 'pantsd.log'

  class StartupFailure(Exception):
    """Represents a failure to start pantsd."""

  class RuntimeFailure(Exception):
    """Represents a pantsd failure at runtime, usually from an underlying service failure."""

  class Factory(object):
    @classmethod
    def create(cls, bootstrap_options=None):
      """
      :param Options bootstrap_options: The bootstrap options, if available.
      """
      bootstrap_options = bootstrap_options or cls._parse_bootstrap_options()
      bootstrap_options_values = bootstrap_options.for_global_scope()

      build_root = get_buildroot()
      native = Native.create(bootstrap_options_values)
      # TODO: https://github.com/pantsbuild/pants/issues/3479
      watchman = WatchmanLauncher.create(bootstrap_options_values).watchman
      legacy_graph_helper = cls._setup_legacy_graph_helper(native, bootstrap_options_values)
      services, port_map = cls._setup_services(
        build_root,
        bootstrap_options_values,
        legacy_graph_helper,
        watchman
      )

      return PantsDaemon(
        native,
        build_root,
        bootstrap_options_values.pants_workdir,
        bootstrap_options_values.level.upper(),
        services,
        port_map,
        bootstrap_options_values.pants_subprocessdir,
        bootstrap_options
      )

    @staticmethod
    def _parse_bootstrap_options():
      return OptionsBootstrapper().get_bootstrap_options()

    @staticmethod
    def _setup_legacy_graph_helper(native, bootstrap_options):
      """Initializes a `LegacyGraphHelper` instance."""
      return EngineInitializer.setup_legacy_graph(
        bootstrap_options.pants_ignore,
        bootstrap_options.pants_workdir,
        bootstrap_options.build_file_imports,
        native=native,
        build_ignore_patterns=bootstrap_options.build_ignore,
        exclude_target_regexps=bootstrap_options.exclude_target_regexp,
        subproject_roots=bootstrap_options.subproject_roots,
      )

    @staticmethod
    def _setup_services(build_root, bootstrap_options, legacy_graph_helper, watchman):
      """Initialize pantsd services.

      :returns: A tuple of (`tuple` service_instances, `dict` port_map).
      """
      fs_event_service = FSEventService(
        watchman,
        build_root,
        bootstrap_options.pantsd_fs_event_workers
      )

      scheduler_service = SchedulerService(
        fs_event_service,
        legacy_graph_helper,
        build_root,
        bootstrap_options.pantsd_invalidation_globs
      )

      pailgun_service = PailgunService(
        bind_addr=(bootstrap_options.pantsd_pailgun_host, bootstrap_options.pantsd_pailgun_port),
        exiter_class=DaemonExiter,
        runner_class=DaemonPantsRunner,
        target_roots_calculator=TargetRootsCalculator,
        scheduler_service=scheduler_service
      )

      store_gc_service = StoreGCService(legacy_graph_helper.scheduler)

      return (
        # Services.
        (fs_event_service, scheduler_service, pailgun_service, store_gc_service),
        # Port map.
        dict(pailgun=pailgun_service.pailgun_port)
      )

  def __init__(self, native, build_root, work_dir, log_level, services, socket_map,
               metadata_base_dir, bootstrap_options=None):
    """
    :param Native native: A `Native` instance.
    :param string build_root: The pants build root.
    :param string work_dir: The pants work directory.
    :param string log_level: The log level to use for daemon logging.
    :param string metadata_base_dir: The ProcessManager metadata base dir.
    :param Options bootstrap_options: The bootstrap options, if available.
    """
    super(PantsDaemon, self).__init__(name='pantsd', metadata_base_dir=metadata_base_dir)
    self._native = native
    self._build_root = build_root
    self._work_dir = work_dir
    self._log_level = log_level
    self._services = services
    self._socket_map = socket_map
    self._bootstrap_options = bootstrap_options

    self._log_dir = os.path.join(work_dir, self.name)
    self._logger = logging.getLogger(__name__)
    # A lock to guard the service thread lifecycles. This can be used by individual services
    # to safeguard daemon-synchronous sections that should be protected from abrupt teardown.
    self._lifecycle_lock = threading.RLock()
    # A lock to guard pantsd->runner forks. This can be used by services to safeguard resources
    # held by threads at fork time, so that we can fork without deadlocking.
    self._fork_lock = threading.RLock()
    # N.B. This Event is used as nothing more than a convenient atomic flag - nothing waits on it.
    self._kill_switch = threading.Event()
    self._exiter = Exiter()

  @memoized_property
  def watchman_launcher(self):
    return WatchmanLauncher.create(self._bootstrap_options.for_global_scope())

  @property
  def is_killed(self):
    return self._kill_switch.is_set()

  @property
  def options_fingerprint(self):
    return OptionsFingerprinter.combined_options_fingerprint_for_scope(
      GLOBAL_SCOPE,
      self._bootstrap_options,
      fingerprint_key='daemon',
      invert=True
    )

  def shutdown(self, service_thread_map):
    """Gracefully terminate all services and kill the main PantsDaemon loop."""
    with self._lifecycle_lock:
      for service, service_thread in service_thread_map.items():
        self._logger.info('terminating pantsd service: {}'.format(service))
        service.terminate()
        service_thread.join(self.JOIN_TIMEOUT_SECONDS)
      self._logger.info('terminating pantsd')
      self._kill_switch.set()

  @staticmethod
  def _close_stdio():
    """Close stdio streams to avoid output in the tty that launched pantsd."""
    for fd in (sys.stdin, sys.stdout, sys.stderr):
      file_no = fd.fileno()
      fd.flush()
      fd.close()
      os.close(file_no)

  @contextmanager
  def _pantsd_logging(self):
    """A context manager that runs with pantsd logging.

    Asserts that stdio (represented by file handles 0, 1, 2) is closed to ensure that
    we can safely reuse those fd numbers.
    """

    # Ensure that stdio is closed so that we can safely reuse those file descriptors.
    for fd in (0, 1, 2):
      try:
        os.fdopen(fd)
        raise AssertionError(
            'pantsd logging cannot initialize while stdio is open: {}'.format(fd))
      except OSError:
        pass

    # Redirect stdio to /dev/null for the rest of the run, to reserve those file descriptors
    # for further forks.
    with stdio_as(stdin_fd=-1, stdout_fd=-1, stderr_fd=-1):
      # Reinitialize logging for the daemon context.
      result = setup_logging(self._log_level, log_dir=self._log_dir, log_name=self.LOG_NAME)

      # Do a python-level redirect of stdout/stderr, which will not disturb `0,1,2`.
      # TODO: Consider giving these pipes/actual fds, in order to make them "deep" replacements
      # for `1,2`, and allow them to be used via `stdio_as`.
      sys.stdout = _LoggerStream(logging.getLogger(), logging.INFO, result.log_handler)
      sys.stderr = _LoggerStream(logging.getLogger(), logging.WARN, result.log_handler)

      self._logger.debug('logging initialized')
      yield result.log_handler.stream

  def _setup_services(self, services):
    assert self._lifecycle_lock is not None, 'PantsDaemon lock has not been set!'
    assert self._fork_lock is not None, 'PantsDaemon fork lock has not been set!'
    for service in services:
      self._logger.info('setting up service {}'.format(service))
      service.setup(self._lifecycle_lock, self._fork_lock)

  @staticmethod
  def _make_thread(target):
    t = threading.Thread(target=target)
    t.daemon = True
    return t

  def _run_services(self, services):
    """Service runner main loop."""
    if not services:
      self._logger.critical('no services to run, bailing!')
      return

    service_thread_map = {service: self._make_thread(service.run) for service in services}

    # Start services.
    for service, service_thread in service_thread_map.items():
      self._logger.info('starting service {}'.format(service))
      try:
        service_thread.start()
      except (RuntimeError, service.ServiceError):
        self.shutdown(service_thread_map)
        raise self.StartupFailure('service {} failed to start, shutting down!'.format(service))

    # Once all services are started, write our pid.
    self.write_pid()
    self.write_metadata_by_name('pantsd', self.FINGERPRINT_KEY, self.options_fingerprint)

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

  def run_sync(self):
    """Synchronously run pantsd."""
    # Switch log output to the daemon's log stream from here forward.
    self._close_stdio()
    with self._pantsd_logging() as log_stream:
      self._exiter.set_except_hook(log_stream)
      self._logger.info('pantsd starting, log level is {}'.format(self._log_level))

      self._native.set_panic_handler()

      # Set the process name in ps output to 'pantsd' vs './pants compile src/etc:: -ldebug'.
      set_process_title('pantsd [{}]'.format(self._build_root))

      # Write service socket information to .pids.
      self._write_named_sockets(self._socket_map)

      # Enter the main service runner loop.
      self._setup_services(self._services)
      self._run_services(self._services)

  def post_fork_child(self):
    """Post-fork() child callback for ProcessManager.daemon_spawn()."""
    entry_point = '{}:launch'.format(__name__)
    exec_env = combined_dict(os.environ, dict(PANTS_ENTRYPOINT=entry_point))
    # Pass all of sys.argv so that we can proxy arg flags e.g. `-ldebug`.
    cmd = [sys.executable] + sys.argv
    self._logger.debug('cmd is: PANTS_ENTRYPOINT={} {}'.format(entry_point, ' '.join(cmd)))
    # TODO: Improve error handling on launch failures.
    os.spawnve(os.P_NOWAIT, sys.executable, cmd, env=exec_env)

  def maybe_launch(self):
    """Launches pantsd (if not already running) in a subprocess.

    :returns: The port that pantsd is listening on.
    :rtype: int
    """
    self.watchman_launcher.maybe_launch()
    self._logger.debug('acquiring lock: {}'.format(self.process_lock))
    with self.process_lock:
      new_fingerprint = self.options_fingerprint
      self._logger.debug('pantsd: is_alive={} new_fingerprint={} current_fingerprint={}'
                         .format(self.is_alive(), new_fingerprint, self.fingerprint))
      if self.needs_restart(new_fingerprint):
        self.terminate(include_watchman=False)
        self._logger.debug('launching pantsd')
        self.daemon_spawn()
        # Wait up to 60 seconds for pantsd to write its pidfile.
        self.await_pid(60)
      listening_port = self.read_named_socket('pailgun', int)
      pantsd_pid = self.pid
    self._logger.debug('released lock: {}'.format(self.process_lock))
    self._logger.debug('pantsd is running at pid {}, pailgun port is {}'
                       .format(pantsd_pid, listening_port))
    return listening_port

  def terminate(self, include_watchman=True):
    """Terminates pantsd and watchman."""
    super(PantsDaemon, self).terminate()
    if include_watchman:
      self.watchman_launcher.terminate()


def launch():
  """An external entrypoint that spawns a new pantsd instance."""
  PantsDaemon.Factory.create().run_sync()
