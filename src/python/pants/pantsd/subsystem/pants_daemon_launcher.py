# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.base.build_environment import get_buildroot
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
               help='Whether or not to use filesystem event detection. Experimental.')
      register('--fs-event-workers', advanced=True, type=int, default=4,
               help='The number of workers to use for the filesystem event service executor pool.'
                    ' Experimental.')

    @classmethod
    def subsystem_dependencies(cls):
      return super(PantsDaemonLauncher.Factory,
                   cls).subsystem_dependencies() + (WatchmanLauncher.Factory, Subprocess.Factory)

    def create(self, engine_initializer=None):
      """
      :param class engine_initializer: The class representing the EngineInitializer. Only necessary
                                       for startup.
      """
      build_root = get_buildroot()
      options = self.global_instance().get_options()
      return PantsDaemonLauncher(build_root=build_root,
                                 pants_workdir=options.pants_workdir,
                                 engine_initializer=engine_initializer,
                                 log_dir=options.log_dir,
                                 log_level=options.level.upper(),
                                 pailgun_host=options.pailgun_host,
                                 pailgun_port=options.pailgun_port,
                                 fs_event_enabled=options.fs_event_detection,
                                 fs_event_workers=options.fs_event_workers,
                                 path_ignore_patterns=options.pants_ignore)

  def __init__(self,
               build_root,
               pants_workdir,
               engine_initializer,
               log_dir,
               log_level,
               pailgun_host,
               pailgun_port,
               fs_event_enabled,
               fs_event_workers,
               path_ignore_patterns):
    """
    :param str build_root: The path of the build root.
    :param str pants_workdir: The path of the pants workdir.
    :param class engine_initializer: The class representing the EngineInitializer.
    :param str log_dir: The path for pantsd logs.
    :param str log_level: The log level for pantsd logs (derived from the pants log level).
    :param str pailgun_host: The bind address for the Pailgun server.
    :param int pailgun_port: The bind port for the Pailgun server.
    :param bool fs_event_enabled: Whether or not to enable fs event detection (Watchman) for graph
                                  invalidation.
    :param int fs_event_workers: The number of workers to use for processing the fs event queue.
    :param list path_ignore_patterns: A list of ignore patterns for filesystem operations.
    """
    self._build_root = build_root
    self._pants_workdir = pants_workdir
    self._engine_initializer = engine_initializer
    self._log_dir = log_dir
    self._log_level = log_level
    self._pailgun_host = pailgun_host
    self._pailgun_port = pailgun_port
    self._fs_event_enabled = fs_event_enabled
    self._fs_event_workers = fs_event_workers
    self._path_ignore_patterns = path_ignore_patterns
    # TODO(kwlzn): Thread filesystem path ignores here to Watchman's subscription registration.

    lock_location = os.path.join(self._build_root, '.pantsd.startup')
    self._lock = OwnerPrintingInterProcessFileLock(lock_location)
    self._logger = logging.getLogger(__name__)

  @testable_memoized_property
  def pantsd(self):
    return PantsDaemon(self._build_root, self._pants_workdir, self._log_level, self._log_dir)

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

    services = []
    scheduler_service = None
    if self._fs_event_enabled:
      fs_event_service = FSEventService(watchman, self._build_root, self._fs_event_workers)

      legacy_graph_helper = self._engine_initializer.setup_legacy_graph(self._path_ignore_patterns)
      scheduler_service = SchedulerService(fs_event_service, legacy_graph_helper)
      services.extend((fs_event_service, scheduler_service))

    pailgun_service = PailgunService(
      bind_addr=(self._pailgun_host, self._pailgun_port),
      exiter_class=DaemonExiter,
      runner_class=DaemonPantsRunner,
      scheduler_service=scheduler_service,
      spec_parser=self._engine_initializer.parse_commandline_to_spec_roots
    )
    services.append(pailgun_service)

    # Construct a mapping of named ports used by the daemon's services. In the default case these
    # will be randomly assigned by the underlying implementation so we can't reference via options.
    port_map = dict(pailgun=pailgun_service.pailgun_port)

    return tuple(services), port_map

  def _launch_pantsd(self):
    # Launch Watchman (if so configured).
    watchman = self.watchman_launcher.maybe_launch() if self._fs_event_enabled else None

    # Initialize pantsd services.
    services, port_map = self._setup_services(watchman)

    # Setup and fork pantsd.
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
    if self._fs_event_enabled:
      self.watchman_launcher.terminate()
