# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.base.build_environment import get_buildroot
from pants.binaries.binary_util import BinaryUtil
from pants.engine.native import Native
from pants.init.target_roots import TargetRoots
from pants.init.util import clean_global_runtime_state
from pants.pantsd.pants_daemon import PantsDaemon
from pants.pantsd.service.fs_event_service import FSEventService
from pants.pantsd.service.pailgun_service import PailgunService
from pants.pantsd.service.scheduler_service import SchedulerService
from pants.pantsd.subsystem.subprocess import Subprocess
from pants.pantsd.subsystem.watchman_launcher import WatchmanLauncher
from pants.process.lock import OwnerPrintingInterProcessFileLock
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import testable_memoized_property


class PantsDaemonLauncher(object):
  """A subsystem that manages the configuration and launching of pantsd."""

  class Factory(Subsystem):
    options_scope = 'pantsd'

    @classmethod
    def register_options(cls, register):
      register('--pailgun-host', advanced=True, default='127.0.0.1',
               help='The host to bind the pants nailgun server to.')
      register('--pailgun-port', advanced=True, type=int, default=0,
               help='The port to bind the pants nailgun server to. Defaults to a random port.')
      register('--log-dir', advanced=True, default=None,
               help='The directory to log pantsd output to.')
      register('--fs-event-detection', advanced=True, type=bool,
               removal_version='1.5.0.dev0',
               removal_hint='This option is now implied by `--enable-pantsd`.',
               help='Whether or not to use filesystem event detection.')
      register('--fs-event-workers', advanced=True, type=int, default=4,
               help='The number of workers to use for the filesystem event service executor pool.')

    @classmethod
    def subsystem_dependencies(cls):
      return super(PantsDaemonLauncher.Factory,
                   cls).subsystem_dependencies() + (WatchmanLauncher.Factory, Subprocess.Factory,
                                                    BinaryUtil.Factory)

    def create(self, engine_initializer=None):
      """
      :param class engine_initializer: The class representing the EngineInitializer. Only necessary
                                       for startup.
      """
      build_root = get_buildroot()
      options = self.global_instance().get_options()
      return PantsDaemonLauncher(build_root=build_root,
                                 engine_initializer=engine_initializer,
                                 options=options)

  def __init__(self,
               build_root,
               engine_initializer,
               options):
    """
    :param str build_root: The path of the build root.
    :param class engine_initializer: The class representing the EngineInitializer.
    """
    self._build_root = build_root
    self._engine_initializer = engine_initializer

    # The options we register directly.
    self._pailgun_host = options.pailgun_host
    self._pailgun_port = options.pailgun_port
    self._log_dir = options.log_dir
    self._fs_event_workers = options.fs_event_workers

    # Values derived from global options (which our scoped options inherit).
    self._pants_workdir = options.pants_workdir
    self._log_level = options.level.upper()
    self._pants_ignore_patterns = options.pants_ignore
    self._build_ignore_patterns = options.build_ignore
    self._exclude_target_regexp = options.exclude_target_regexp
    self._subproject_roots = options.subproject_roots
    # Native.create() reads global options, which, thanks to inheritance, it can
    # read them via our scoped options.
    self._native = Native.create(options)
    # TODO(kwlzn): Thread filesystem path ignores here to Watchman's subscription registration.

    lock_location = os.path.join(self._build_root, '.pantsd.startup')
    self._lock = OwnerPrintingInterProcessFileLock(lock_location)
    self._logger = logging.getLogger(__name__)

  @testable_memoized_property
  def pantsd(self):
    return PantsDaemon(
      self._build_root,
      self._pants_workdir,
      self._log_level,
      self._native,
      self._log_dir,
      reset_func=clean_global_runtime_state
    )

  @testable_memoized_property
  def watchman_launcher(self):
    return WatchmanLauncher.Factory.global_instance().create()

  def _setup_services(self, watchman):
    """Initialize pantsd services.

    :returns: A tuple of (`tuple` service_instances, `dict` port_map).
    """
    # N.B. This inline import is currently necessary to avoid a circular reference in the import
    # of LocalPantsRunner for use by DaemonPantsRunner. This is because LocalPantsRunner must
    # ultimately import the pantsd services in order to itself launch pantsd.
    from pants.bin.daemon_pants_runner import DaemonExiter, DaemonPantsRunner

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
    self.pantsd.daemonize()

    # Wait up to 10 seconds for pantsd to write its pidfile so we can display the pid to the user.
    self.pantsd.await_pid(10)

  def maybe_launch(self):
    self._logger.debug('acquiring lock: {}'.format(self._lock))
    with self._lock:
      if not self.pantsd.is_alive():
        self._logger.debug('launching pantsd')
        self._launch_pantsd()
    self._logger.debug('released lock: {}'.format(self._lock))

    self._logger.debug('pantsd is running at pid {}'.format(self.pantsd.pid))

  def terminate(self):
    self.pantsd.terminate()
    self.watchman_launcher.terminate()
