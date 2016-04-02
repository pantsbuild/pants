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
from pants.pantsd.subsystem.watchman_launcher import WatchmanLauncher
from pants.process.lock import OwnerPrintingInterProcessFileLock
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import testable_memoized_property


class PantsDaemonLauncher(Subsystem):
  """A subsystem that manages the configuration and launching of pantsd."""

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
    return super(PantsDaemonLauncher, cls).subsystem_dependencies() + (WatchmanLauncher.Factory,)

  def __init__(self, *args, **kwargs):
    super(PantsDaemonLauncher, self).__init__(*args, **kwargs)
    self._logger = logging.getLogger(__name__)
    self._build_root = get_buildroot()

    options = self.get_options()
    self._pants_workdir = options.pants_workdir
    self._log_dir = options.log_dir
    self._log_level = options.level.upper()
    self._pailgun_host = options.pailgun_host
    self._pailgun_port = options.pailgun_port
    self._fs_event_enabled = options.fs_event_detection
    self._fs_event_workers = options.fs_event_workers

    self._pantsd = None
    self._scheduler = None
    self._lock = OwnerPrintingInterProcessFileLock(
      os.path.join(self._build_root, '.pantsd.startup'))

  @testable_memoized_property
  def pantsd(self):
    return PantsDaemon(self._build_root, self._pants_workdir, self._log_level, self._log_dir)

  @testable_memoized_property
  def watchman_launcher(self):
    return WatchmanLauncher.Factory.global_instance().create()

  def set_scheduler(self, scheduler):
    self._scheduler = scheduler

  def _setup_services(self, watchman):
    """Initialize pantsd services.

    :returns: A tuple of (`tuple` service_instances, `dict` port_map).
    """
    # N.B. This inline import is currently necessary to avoid a circular reference in the import
    # of LocalPantsRunner for use by DaemonPantsRunner. This is because LocalPantsRunner must
    # ultimately import the pantsd services in order to itself launch pantsd.
    from pants.bin.daemon_pants_runner import DaemonExiter, DaemonPantsRunner

    pailgun_service = PailgunService((self._pailgun_host, self._pailgun_port),
                                     DaemonExiter,
                                     DaemonPantsRunner)
    services = [pailgun_service]

    if self._fs_event_enabled and self._scheduler:
      fs_event_service = FSEventService(watchman, self._build_root, self._fs_event_workers)
      scheduler_service = SchedulerService(self._scheduler, fs_event_service)
      services.extend((fs_event_service, scheduler_service))

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
