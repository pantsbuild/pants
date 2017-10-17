# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.base.build_environment import get_buildroot
from pants.bin.daemon_pants_runner import DaemonExiter, DaemonPantsRunner
from pants.engine.native import Native
from pants.init.target_roots import TargetRoots
from pants.init.util import clean_global_runtime_state
from pants.pantsd.pants_daemon import PantsDaemon
from pants.pantsd.service.fs_event_service import FSEventService
from pants.pantsd.service.pailgun_service import PailgunService
from pants.pantsd.service.scheduler_service import SchedulerService
from pants.pantsd.watchman_launcher import WatchmanLauncher
from pants.process.lock import OwnerPrintingInterProcessFileLock
from pants.util.memo import testable_memoized_property


class PantsDaemonLauncher(object):
  """An object that manages the configuration and lifecycle of pantsd."""

  def __init__(self, bootstrap_options, engine_initializer=None):
    """
    :param Options bootstrap_options: An Options object containing the bootstrap options.
    :param class engine_initializer: The class representing the EngineInitializer. Only required
                                     for startup.
    """
    self._bootstrap_options = bootstrap_options
    self._engine_initializer = engine_initializer

    self._pailgun_host = bootstrap_options.pantsd_pailgun_host
    self._pailgun_port = bootstrap_options.pantsd_pailgun_port
    self._log_dir = bootstrap_options.pantsd_log_dir
    self._fs_event_workers = bootstrap_options.pantsd_fs_event_workers
    self._pants_workdir = bootstrap_options.pants_workdir
    self._log_level = bootstrap_options.level.upper()
    self._pants_ignore_patterns = bootstrap_options.pants_ignore
    self._build_ignore_patterns = bootstrap_options.build_ignore
    self._exclude_target_regexp = bootstrap_options.exclude_target_regexp
    self._subproject_roots = bootstrap_options.subproject_roots
    self._metadata_base_dir = bootstrap_options.pants_subprocessdir

    # TODO: https://github.com/pantsbuild/pants/issues/3479
    self._build_root = get_buildroot()
    self._native = Native.create(bootstrap_options)
    self._logger = logging.getLogger(__name__)
    self._lock = OwnerPrintingInterProcessFileLock(
      os.path.join(self._build_root, '.pantsd.startup')
    )

  @testable_memoized_property
  def pantsd(self):
    return PantsDaemon(
      self._build_root,
      self._pants_workdir,
      self._log_level,
      self._native,
      self._log_dir,
      reset_func=clean_global_runtime_state,
      metadata_base_dir=self._metadata_base_dir
    )

  @testable_memoized_property
  def watchman_launcher(self):
    return WatchmanLauncher.create(self._bootstrap_options)

  def _setup_services(self, watchman):
    """Initialize pantsd services.

    :returns: A tuple of (`tuple` service_instances, `dict` port_map).
    """
    legacy_graph_helper = self._engine_initializer.setup_legacy_graph(
      self._pants_ignore_patterns,
      self._pants_workdir,
      native=self._native,
      build_ignore_patterns=self._build_ignore_patterns,
      exclude_target_regexps=self._exclude_target_regexp,
      subproject_roots=self._subproject_roots,
    )

    fs_event_service = FSEventService(watchman, self._build_root, self._fs_event_workers)
    scheduler_service = SchedulerService(fs_event_service, legacy_graph_helper)
    pailgun_service = PailgunService(
      bind_addr=(self._pailgun_host, self._pailgun_port),
      exiter_class=DaemonExiter,
      runner_class=DaemonPantsRunner,
      target_roots_class=TargetRoots,
      scheduler_service=scheduler_service
    )

    return (
      # Use the schedulers reentrant lock as the daemon's global lock.
      legacy_graph_helper.scheduler.lock,
      # Services.
      (fs_event_service, scheduler_service, pailgun_service),
      # Port map.
      dict(pailgun=pailgun_service.pailgun_port)
    )

  def _launch_pantsd(self):
    # Launch Watchman (if so configured).
    watchman = self.watchman_launcher.maybe_launch()

    # Initialize pantsd services.
    lock, services, port_map = self._setup_services(watchman)

    # Setup and fork pantsd.
    self.pantsd.set_lock(lock)
    self.pantsd.set_services(services)
    self.pantsd.set_socket_map(port_map)
    # Defer pid writing until the daemon has fully spawned.
    self.pantsd.daemonize(write_pid=False)

    # Wait up to 10 seconds for pantsd to write its pidfile so we can display the pid to the user.
    self.pantsd.await_pid(10)

  def maybe_launch(self):
    """Launches pantsd if not already running.

    :returns: The port that pantsd is listening on.
    :rtype: int
    """
    self._logger.debug('acquiring lock: {}'.format(self._lock))
    with self._lock:
      if not self.pantsd.is_alive():
        self._logger.debug('launching pantsd')
        self._launch_pantsd()
      listening_port = self.pantsd.read_named_socket('pailgun', int)
      pantsd_pid = self.pantsd.pid
    self._logger.debug('released lock: {}'.format(self._lock))
    self._logger.debug('pantsd is running at pid {}, pailgun port is {}'
                       .format(pantsd_pid, listening_port))
    return listening_port

  def terminate(self):
    self.pantsd.terminate()
    self.watchman_launcher.terminate()
