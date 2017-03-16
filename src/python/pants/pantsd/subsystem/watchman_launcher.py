# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.binaries.binary_util import BinaryUtil
from pants.pantsd.subsystem.subprocess import Subprocess
from pants.pantsd.watchman import Watchman
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import testable_memoized_property


class WatchmanLauncher(object):
  """A subsystem that encapsulates access to Watchman."""

  class Factory(Subsystem):
    options_scope = 'watchman'

    @classmethod
    def subsystem_dependencies(cls):
      return (BinaryUtil.Factory, Subprocess.Factory)

    @classmethod
    def register_options(cls, register):
      register('--version', advanced=True, default='4.5.0',
               help='Watchman version.')
      register('--supportdir', advanced=True, default='bin/watchman',
               help='Find watchman binaries under this dir. Used as part of the path to lookup '
                    'the binary with --binary-util-baseurls and --pants-bootstrapdir.')
      register('--startup-timeout', type=float, advanced=True, default=Watchman.STARTUP_TIMEOUT_SECONDS,
               help='The watchman socket timeout (in seconds) for the initial `watch-project` command. '
                    'This may need to be set higher for larger repos due to watchman startup cost.')
      register('--socket-timeout', type=float, advanced=True, default=Watchman.SOCKET_TIMEOUT_SECONDS,
               help='The watchman client socket timeout (in seconds).')
      register('--socket-path', type=str, advanced=True, default=None,
               help='The path to the watchman UNIX socket. This can be overridden if the default '
                    'absolute path length exceeds the maximum allowed by the OS.')

    def create(self):
      binary_util = BinaryUtil.Factory.create()
      options = self.get_options()
      return WatchmanLauncher(binary_util,
                              options.pants_workdir,
                              options.level,
                              options.version,
                              options.supportdir,
                              options.startup_timeout,
                              options.socket_timeout,
                              options.socket_path)

  def __init__(self, binary_util, workdir, log_level, watchman_version, watchman_supportdir,
               startup_timeout, socket_timeout, socket_path_override=None):
    """
    :param binary_util: The BinaryUtil subsystem instance for binary retrieval.
    :param workdir: The current pants workdir.
    :param log_level: The current log level of pants.
    :param watchman_version: The watchman binary version to retrieve using BinaryUtil.
    :param watchman_supportdir: The supportdir for BinaryUtil.
    :param socket_timeout: The watchman client socket timeout (in seconds).
    :param socket_path_override: The overridden target path of the watchman socket, if any.
    """
    self._binary_util = binary_util
    self._workdir = workdir
    self._watchman_version = watchman_version
    self._watchman_supportdir = watchman_supportdir
    self._startup_timeout = startup_timeout
    self._socket_timeout = socket_timeout
    self._socket_path_override = socket_path_override
    self._log_level = log_level
    self._logger = logging.getLogger(__name__)
    self._watchman = None

  @staticmethod
  def _convert_log_level(level):
    """Convert a given pants log level string into a watchman log level string."""
    # N.B. Enabling true Watchman debug logging (log level 2) can generate an absurd amount of log
    # data (10s of gigabytes over the course of an ~hour for an active fs) and is not particularly
    # helpful except for debugging Watchman itself. Thus, here we intentionally avoid this level
    # in the mapping of pants log level -> watchman.
    return {'warn': '0', 'info': '1', 'debug': '1'}.get(level, '1')

  @testable_memoized_property
  def watchman(self):
    watchman_binary = self._binary_util.select_binary(self._watchman_supportdir,
                                                      self._watchman_version,
                                                      'watchman')
    return Watchman(watchman_binary,
                    self._workdir,
                    self._convert_log_level(self._log_level),
                    self._startup_timeout,
                    self._socket_timeout,
                    self._socket_path_override)

  def maybe_launch(self):
    if not self.watchman.is_alive():
      self._logger.debug('launching watchman')
      try:
        self.watchman.launch()
      except (self.watchman.ExecutionError, self.watchman.InvalidCommandOutput) as e:
        self._logger.fatal('failed to launch watchman: {!r})'.format(e))
        raise

    self._logger.debug('watchman is running, pid={pid} socket={socket}'
                       .format(pid=self.watchman.pid, socket=self.watchman.socket))
    return self.watchman

  def terminate(self):
    self.watchman.terminate()
