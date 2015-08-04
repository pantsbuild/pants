# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.pantsd.watchman import Watchman
from pants.subsystem.subsystem import Subsystem


class WatchmanLauncher(Subsystem):
  """Watchman launcher subsystem."""

  options_scope = 'watchman'

  @classmethod
  def register_options(cls, register):
    register('--watchman-path', type=str, advanced=True, default=None, action='store',
             help='Watchman binary location (defaults to $PATH discovery).')
    register('--log-level', type=int, advanced=True, default=1, action='store',
             help='Watchman log level (0=off, 1=normal, 2=verbose).')

  def __init__(self, *args, **kwargs):
    Subsystem.__init__(self, *args, **kwargs)
    self._logger = logging.getLogger()
    self.options = self.get_options()
    self.watchman = Watchman(self.options)

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
    return True
