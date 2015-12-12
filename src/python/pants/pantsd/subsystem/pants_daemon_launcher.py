# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.base.build_environment import get_buildroot
from pants.pantsd.pants_daemon import PantsDaemon
from pants.pantsd.service.pailgun_service import PailgunService
from pants.process.pidlock import OwnerPrintingPIDLockFile
from pants.subsystem.subsystem import Subsystem


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

  def __init__(self, *args, **kwargs):
    super(PantsDaemonLauncher, self).__init__(*args, **kwargs)
    self.options = self.get_options()
    self._logger = logging.getLogger(__name__)
    self._build_root = get_buildroot()
    self._pants_workdir = self.options.pants_workdir
    self._log_dir = self.options.log_dir
    self._log_level = self.options.level.upper()
    self._pailgun_host = self.options.pailgun_host
    self._pailgun_port = self.options.pailgun_port
    self._pantsd = None
    self._lock = OwnerPrintingPIDLockFile(os.path.join(self._build_root, '.pantsd.startup'))

  @property
  def pantsd(self):
    if not self._pantsd:
      self._pantsd = PantsDaemon(self._build_root,
                                 self._pants_workdir,
                                 self._log_level,
                                 self._log_dir)
    return self._pantsd

  def _setup_services(self):
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

    # Construct a mapping of named ports used by the daemon's services. In the default case these
    # will be randomly assigned by the underlying implementation so we can't reference via options.
    port_map = dict(pailgun=pailgun_service.pailgun_port)
    services = (pailgun_service,)

    return services, port_map

  def _launch_pantsd(self):
    # Initialize pantsd services.
    services, port_map = self._setup_services()

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
