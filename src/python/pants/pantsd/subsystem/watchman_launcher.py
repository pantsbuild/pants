# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import time

from pants.binaries.binary_util import BinaryUtil
from pants.pantsd.watchman import Watchman
from pants.subsystem.subsystem import Subsystem


class WatchmanLauncher(Subsystem):
  """Watchman launcher subsystem."""

  options_scope = 'watchman'

  @classmethod
  def register_options(cls, register):
    register('--version', type=str, advanced=True, default='4.5.0', action='store',
             help='Watchman version.')
    register('--supportdir', advanced=True, default='bin/watchman',
             help='Find watchman binaries under this dir. Used as part of the path to lookup '
                  'the binary with --binary-util-baseurls and --pants-bootstrapdir.')

  def __init__(self, *args, **kwargs):
    super(WatchmanLauncher, self).__init__(*args, **kwargs)

    options = self.get_options()
    self._workdir = options.pants_workdir
    self._watchman_version = options.version
    self._watchman_supportdir = options.supportdir
    # N.B. watchman has 3 log levels: 0 == no logging, 1 == standard logging, 2 == verbose logging.
    self._watchman_log_level = '2' if options.level == 'debug' else '1'

    self._logger = logging.getLogger(__name__)
    self._watchman = None

  @classmethod
  def global_subsystems(cls):
    return super(WatchmanLauncher, cls).global_subsystems() + (BinaryUtil.Factory,)

  @property
  def watchman(self):
    if not self._watchman:
      self._watchman = Watchman(self._workdir,
                                self._watchman_binary(),
                                log_level=self._watchman_log_level)
    return self._watchman

  def _watchman_binary(self):
    binary_util = BinaryUtil.Factory.create()
    return binary_util.select_binary(self._watchman_supportdir, self._watchman_version, 'watchman')

  def maybe_launch(self):
    if not self.watchman.is_alive():
      self._logger.info('launching watchman at {path}'.format(path=self.watchman.watchman_path))
      try:
        self.watchman.launch()
      except (self.watchman.ExecutionError, self.watchman.InvalidCommandOutput) as e:
        self._logger.critical('failed to launch watchman: {exc!r})'.format(exc=e))
        return False

    self._logger.info('watchman is running, pid={pid} socket={socket}'
                      .format(pid=self.watchman.pid, socket=self.watchman.socket))
    # TODO(kwlzn): This sleep is currently helpful based on empirical testing with older watchman
    # versions, but should go away quickly once we embed watchman fetching in pants and uprev both
    # the binary and client versions.
    time.sleep(5)  # Allow watchman to quiesce before sending commands.
    return self.watchman

  def terminate(self):
    self.watchman.terminate()
