# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import sys
import threading
from builtins import object
from contextlib import contextmanager

from future.utils import text_type
from setproctitle import setproctitle as set_process_title

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink, SignalHandler
from pants.base.exiter import Exiter
from pants.bin.daemon_pants_runner import DaemonPantsRunner
from pants.engine.native import Native
from pants.init.engine_initializer import EngineInitializer
from pants.init.logging import init_rust_logger, setup_logging
from pants.init.options_initializer import BuildConfigInitializer
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.options_fingerprinter import OptionsFingerprinter
from pants.pantsd.process_manager import FingerprintedProcessManager
from pants.pantsd.service.fs_event_service import FSEventService
from pants.pantsd.service.pailgun_service import PailgunService
from pants.pantsd.service.pants_service import PantsServices
from pants.pantsd.service.scheduler_service import SchedulerService
from pants.pantsd.service.store_gc_service import StoreGCService
from pants.pantsd.watchman_launcher import WatchmanLauncher
from pants.util.collections import combined_dict
from pants.util.contextutil import stdio_as
from pants.util.memo import memoized_property
from pants.util.objects import datatype
from pants.util.strutil import ensure_text


class _LoggerStream(object):
  """A sys.std{out,err} replacement that pipes output to a logger.

  N.B. `logging.Logger` expects unicode. However, most of our outstream logic, such as in `Exiter.py`,
  will use `sys.std{out,err}.buffer` and thus a bytes interface when running with Python 3. So, we must provide
  a `buffer` property, and change the semantics of the buffer to always convert the message to unicode. This
  is an unfortunate code smell, as `logging` does not expose a bytes interface so this is
  the best solution we could think of.
  """

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
    msg = ensure_text(msg)
    for line in msg.rstrip().splitlines():
      # The log only accepts text, and will raise a decoding error if the default encoding is ascii
      # if provided a bytes input for unicode text.
      line = ensure_text(line)
      self._logger.log(self._log_level, line.rstrip())

  def flush(self):
    return

  def isatty(self):
    return False

  def fileno(self):
    return self._handler.stream.fileno()

  @property
  def buffer(self):
    return self


class PantsDaemonSignalHandler(SignalHandler):

  def __init__(self, daemon):
    super(PantsDaemonSignalHandler, self).__init__()
    self._daemon = daemon

  def handle_sigint(self, signum, _frame):
    self._daemon.terminate(include_watchman=False)


class PantsDaemon(FingerprintedProcessManager):
  """A daemon that manages PantsService instances."""

  JOIN_TIMEOUT_SECONDS = 1
  LOG_NAME = 'pantsd.log'

  class StartupFailure(Exception):
    """Represents a failure to start pantsd."""

  class RuntimeFailure(Exception):
    """Represents a pantsd failure at runtime, usually from an underlying service failure."""

  class Handle(datatype([('pid', int), ('port', int), ('metadata_base_dir', text_type)])):
    """A handle to a "probably running" pantsd instance.

    We attempt to verify that the pantsd instance is still running when we create a Handle, but
    after it has been created it is entirely process that the pantsd instance perishes.
    """

  class Factory(object):
    @classmethod
    def maybe_launch(cls, options_bootstrapper):
      """Creates and launches a daemon instance if one does not already exist.

      :param OptionsBootstrapper options_bootstrapper: The bootstrap options.
      :returns: A Handle for the running pantsd instance.
      :rtype: PantsDaemon.Handle
      """
      stub_pantsd = cls.create(options_bootstrapper, full_init=False)
      with stub_pantsd._services.lifecycle_lock:
        if stub_pantsd.needs_restart(stub_pantsd.options_fingerprint):
          # Once we determine we actually need to launch, recreate with full initialization.
          pantsd = cls.create(options_bootstrapper)
          return pantsd.launch()
        else:
          # We're already launched.
          return PantsDaemon.Handle(
              stub_pantsd.await_pid(10),
              stub_pantsd.read_named_socket('pailgun', int),
              text_type(stub_pantsd._metadata_base_dir),
          )

    @classmethod
    def restart(cls, options_bootstrapper):
      """Restarts a running daemon instance.

      :param OptionsBootstrapper options_bootstrapper: The bootstrap options.
      :returns: A Handle for the pantsd instance.
      :rtype: PantsDaemon.Handle
      """
      pantsd = cls.create(options_bootstrapper)
      with pantsd._services.lifecycle_lock:
        # N.B. This will call `pantsd.terminate()` before starting.
        return pantsd.launch()

    @classmethod
    def create(cls, options_bootstrapper, full_init=True):
      """
      :param OptionsBootstrapper options_bootstrapper: The bootstrap options.
      :param bool full_init: Whether or not to fully initialize an engine et al for the purposes
                             of spawning a new daemon. `full_init=False` is intended primarily
                             for lightweight lifecycle checks (since there is a ~1s overhead to
                             initialize the engine). See the impl of `maybe_launch` for an example
                             of the intended usage.
      """
      bootstrap_options = options_bootstrapper.bootstrap_options
      bootstrap_options_values = bootstrap_options.for_global_scope()
      # TODO: https://github.com/pantsbuild/pants/issues/3479
      watchman = WatchmanLauncher.create(bootstrap_options_values).watchman

      if full_init:
        build_root = get_buildroot()
        native = Native()
        build_config = BuildConfigInitializer.get(options_bootstrapper)
        legacy_graph_scheduler = EngineInitializer.setup_legacy_graph(native,
                                                                      options_bootstrapper,
                                                                      build_config)
        services = cls._setup_services(
          build_root,
          bootstrap_options_values,
          legacy_graph_scheduler,
          watchman
        )
      else:
        build_root = None
        native = None
        services = PantsServices()

      return PantsDaemon(
        native=native,
        build_root=build_root,
        work_dir=bootstrap_options_values.pants_workdir,
        log_level=bootstrap_options_values.level.upper(),
        services=services,
        metadata_base_dir=bootstrap_options_values.pants_subprocessdir,
        bootstrap_options=bootstrap_options
      )

    @staticmethod
    def _setup_services(build_root, bootstrap_options, legacy_graph_scheduler, watchman):
      """Initialize pantsd services.

      :returns: A PantsServices instance.
      """
      should_shutdown_after_run = bootstrap_options.shutdown_pantsd_after_run
      fs_event_service = FSEventService(
        watchman,
        build_root,
      )

      pidfile_absolute = PantsDaemon.metadata_file_path('pantsd', 'pid', bootstrap_options.pants_subprocessdir)
      if pidfile_absolute.startswith(build_root):
        pidfile = os.path.relpath(pidfile_absolute, build_root)
      else:
        pidfile = None
        logging.getLogger(__name__).warning(
          'Not watching pantsd pidfile because subprocessdir is outside of buildroot. Having '
          'subprocessdir be a child of buildroot (as it is by default) may help avoid stray '
          'pantsd processes.'
        )

      scheduler_service = SchedulerService(
        fs_event_service,
        legacy_graph_scheduler,
        build_root,
        PantsDaemon.compute_invalidation_globs(bootstrap_options),
        pidfile,
      )

      pailgun_service = PailgunService(
        (bootstrap_options.pantsd_pailgun_host, bootstrap_options.pantsd_pailgun_port),
        DaemonPantsRunner,
        scheduler_service,
        should_shutdown_after_run
      )

      store_gc_service = StoreGCService(legacy_graph_scheduler.scheduler)

      return PantsServices(
        services=(fs_event_service, scheduler_service, pailgun_service, store_gc_service),
        port_map=dict(pailgun=pailgun_service.pailgun_port),
      )

  @staticmethod
  def compute_invalidation_globs(bootstrap_options):
    """
    Combine --pythonpath and --pants_config_files(pants.ini) files that are in {buildroot} dir
    with those invalidation_globs provided by users
    :param bootstrap_options:
    :return: A list of invalidation_globs
    """
    buildroot = get_buildroot()
    invalidation_globs = []
    globs = bootstrap_options.pythonpath + \
      bootstrap_options.pants_config_files + \
      bootstrap_options.pantsd_invalidation_globs

    for glob in globs:
      glob_relpath = os.path.relpath(glob, buildroot)
      if glob_relpath and (not glob_relpath.startswith("../")):
        invalidation_globs.extend([glob_relpath, glob_relpath + '/**'])
      else:
        logging.getLogger(__name__).warning("Changes to {}, outside of the buildroot"
                                            ", will not be invalidated.".format(glob))

    return invalidation_globs

  def __init__(self, native, build_root, work_dir, log_level, services,
               metadata_base_dir, bootstrap_options=None):
    """
    :param Native native: A `Native` instance.
    :param string build_root: The pants build root.
    :param string work_dir: The pants work directory.
    :param string log_level: The log level to use for daemon logging.
    :param PantsServices services: A registry of services to use in this run.
    :param string metadata_base_dir: The ProcessManager metadata base dir.
    :param Options bootstrap_options: The bootstrap options, if available.
    """
    super(PantsDaemon, self).__init__(name='pantsd', metadata_base_dir=metadata_base_dir)
    self._native = native
    self._build_root = build_root
    self._work_dir = work_dir
    self._log_level = log_level
    self._services = services
    self._bootstrap_options = bootstrap_options
    self._log_show_rust_3rdparty = bootstrap_options.for_global_scope().log_show_rust_3rdparty if bootstrap_options else True

    self._log_dir = os.path.join(work_dir, self.name)
    self._logger = logging.getLogger(__name__)
    # N.B. This Event is used as nothing more than a convenient atomic flag - nothing waits on it.
    self._kill_switch = threading.Event()

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
    with self._services.lifecycle_lock:
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
      init_rust_logger(self._log_level, self._log_show_rust_3rdparty)
      result = setup_logging(self._log_level, log_dir=self._log_dir, log_name=self.LOG_NAME, native=self._native)
      self._native.override_thread_logging_destination_to_just_pantsd()

      # Do a python-level redirect of stdout/stderr, which will not disturb `0,1,2`.
      # TODO: Consider giving these pipes/actual fds, in order to make them "deep" replacements
      # for `1,2`, and allow them to be used via `stdio_as`.
      sys.stdout = _LoggerStream(logging.getLogger(), logging.INFO, result.log_handler)
      sys.stderr = _LoggerStream(logging.getLogger(), logging.WARN, result.log_handler)

      self._logger.debug('logging initialized')
      yield (result.log_handler.stream, result.log_handler.native_filename)

  def _setup_services(self, pants_services):
    for service in pants_services.services:
      self._logger.info('setting up service {}'.format(service))
      service.setup(self._services)

  @staticmethod
  def _make_thread(service):
    name = "{}Thread".format(service.__class__.__name__)

    def target():
      Native().override_thread_logging_destination_to_just_pantsd()
      service.run()

    t = threading.Thread(target=target, name=name)
    t.daemon = True
    return t

  def _run_services(self, pants_services):
    """Service runner main loop."""
    if not pants_services.services:
      self._logger.critical('no services to run, bailing!')
      return

    service_thread_map = {service: self._make_thread(service)
                          for service in pants_services.services}

    # Start services.
    for service, service_thread in service_thread_map.items():
      self._logger.info('starting service {}'.format(service))
      try:
        service_thread.start()
      except (RuntimeError, FSEventService.ServiceError):
        self.shutdown(service_thread_map)
        raise PantsDaemon.StartupFailure('service {} failed to start, shutting down!'.format(service))

    # Once all services are started, write our pid.
    self.write_pid()
    self.write_metadata_by_name('pantsd', self.FINGERPRINT_KEY, ensure_text(self.options_fingerprint))

    # Monitor services.
    while not self.is_killed:
      for service, service_thread in service_thread_map.items():
        if not service_thread.is_alive():
          self.shutdown(service_thread_map)
          raise PantsDaemon.RuntimeFailure('service failure for {}, shutting down!'.format(service))
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
    with self._pantsd_logging() as (log_stream, log_filename):

      # Register an exiter using os._exit to ensure we only close stdio streams once.
      ExceptionSink.reset_exiter(Exiter(exiter=os._exit))

      # We don't have any stdio streams to log to anymore, so we log to a file.
      # We don't override the faulthandler destination because the stream we get will proxy things
      # via the rust logging code, and faulthandler needs to be writing directly to a real file
      # descriptor. When pantsd logging was originally initialised, we already set up faulthandler
      # to log to the correct file descriptor, so don't override it.
      #
      # We can get tracebacks of the pantsd process by tailing the pantsd log and sending it
      # SIGUSR2.
      ExceptionSink.reset_interactive_output_stream(
        log_stream,
        override_faulthandler_destination=False,
      )

      # Reset the log location and the backtrace preference from the global bootstrap options.
      global_bootstrap_options = self._bootstrap_options.for_global_scope()
      ExceptionSink.reset_should_print_backtrace_to_terminal(
        global_bootstrap_options.print_exception_stacktrace)
      ExceptionSink.reset_log_location(global_bootstrap_options.pants_workdir)

      self._native.set_panic_handler()

      # Set the process name in ps output to 'pantsd' vs './pants compile src/etc:: -ldebug'.
      set_process_title('pantsd [{}]'.format(self._build_root))

      # Write service socket information to .pids.
      self._write_named_sockets(self._services.port_map)

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

  def needs_launch(self):
    """Determines if pantsd needs to be launched.

    N.B. This should always be called under care of the `lifecycle_lock`.

    :returns: True if the daemon needs launching, False otherwise.
    :rtype: bool
    """
    new_fingerprint = self.options_fingerprint
    self._logger.debug('pantsd: is_alive={} new_fingerprint={} current_fingerprint={}'
                       .format(self.is_alive(), new_fingerprint, self.fingerprint))
    return self.needs_restart(new_fingerprint)

  def launch(self):
    """Launches pantsd in a subprocess.

    N.B. This should always be called under care of the `lifecycle_lock`.

    :returns: A Handle for the pantsd instance.
    :rtype: PantsDaemon.Handle
    """
    self.terminate(include_watchman=False)
    self.watchman_launcher.maybe_launch()
    self._logger.debug('launching pantsd')
    self.daemon_spawn()
    # Wait up to 60 seconds for pantsd to write its pidfile.
    pantsd_pid = self.await_pid(60)
    listening_port = self.read_named_socket('pailgun', int)
    self._logger.debug('pantsd is running at pid {}, pailgun port is {}'
                       .format(self.pid, listening_port))
    return self.Handle(pantsd_pid, listening_port, text_type(self._metadata_base_dir))

  def terminate(self, include_watchman=True):
    """Terminates pantsd and watchman.

    N.B. This should always be called under care of the `lifecycle_lock`.
    """
    super(PantsDaemon, self).terminate()
    if include_watchman:
      self.watchman_launcher.terminate()

  def needs_restart(self, option_fingerprint):
    """
    Overrides ProcessManager.needs_restart, to account for the case where pantsd is running
    but we want to shutdown after this run.
    :param option_fingerprint: A fingeprint of the global bootstrap options.
    :return: True if the daemon needs to restart.
    """
    should_shutdown_after_run = self._bootstrap_options.for_global_scope().shutdown_pantsd_after_run
    return super(PantsDaemon, self).needs_restart(option_fingerprint) or \
           (self.is_alive() and should_shutdown_after_run)


def launch():
  """An external entrypoint that spawns a new pantsd instance."""
  PantsDaemon.Factory.create(OptionsBootstrapper.create()).run_sync()
