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
from pants.util.memo import testable_memoized_property


class WatchmanLauncher(object):
  """Encapsulates access to Watchman."""

  class Factory(Subsystem):
    options_scope = 'watchman'

    @classmethod
    def subsystem_dependencies(cls):
      return (BinaryUtil.Factory,)

    @classmethod
    def register_options(cls, register):
      register('--version', advanced=True, default='4.5.0',
               help='Watchman version.')
      register('--supportdir', advanced=True, default='bin/watchman',
               help='Find watchman binaries under this dir. Used as part of the path to lookup '
                    'the binary with --binary-util-baseurls and --pants-bootstrapdir.')

    def create(self):
      binary_util = BinaryUtil.Factory.create()
      options = self.get_options()
      return WatchmanLauncher(binary_util,
                              options.pants_workdir,
                              options.level,
                              options.version,
                              options.supportdir)

  def __init__(self, binary_util, workdir, log_level, watchman_version, watchman_supportdir):
    """
    :param binary_util: The BinaryUtil subsystem instance for binary retrieval.
    :param workdir: The current pants workdir.
    :param log_level: The current log level of pants.
    :param watchman_version: The watchman binary version to retrieve using BinaryUtil.
    :param watchman_supportdir: The supportdir for BinaryUtil.
    """
    self._binary_util = binary_util
    self._workdir = workdir
    self._watchman_version = watchman_version
    self._watchman_supportdir = watchman_supportdir
    self._log_level = log_level
    self._logger = logging.getLogger(__name__)
    self._watchman = None

  @staticmethod
  def _convert_log_level(level):
    """Convert a given pants log level string into a watchman log level string."""
    return {'warn': '0', 'info': '1', 'debug': '2'}.get(level, '1')

  @testable_memoized_property
  def watchman(self):
    watchman_binary = self._binary_util.select_binary(self._watchman_supportdir,
                                                      self._watchman_version,
                                                      'watchman')
    return Watchman(watchman_binary,
                    self._workdir,
                    self._convert_log_level(self._log_level))

  def maybe_launch(self):
    if not self.watchman.is_alive():
      self._logger.info('launching watchman')
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
