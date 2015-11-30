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
    # TODO (kwlzn): this will go away quickly once watchman binary embedding happens.
    register('--path', type=str, advanced=True, default=None, action='store',
             help='Watchman binary location (defaults to $PATH discovery).')

  def __init__(self, *args, **kwargs):
    super(WatchmanLauncher, self).__init__(*args, **kwargs)

    options = self.get_options()
    self._workdir = options.pants_workdir
    self._watchman_path = options.path
    # N.B. watchman has 3 log levels: 0 == no logging, 1 == standard logging, 2 == verbose logging.
    self._watchman_log_level = '2' if options.level == 'debug' else '1'

    self._logger = logging.getLogger(__name__)
    self._watchman = None

  @property
  def watchman(self):
    if not self._watchman:
      self._watchman = Watchman(self._workdir,
                                log_level=self._watchman_log_level,
                                watchman_path=self._watchman_path)
    return self._watchman

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
    return self.watchman
