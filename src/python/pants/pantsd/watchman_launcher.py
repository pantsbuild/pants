# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.binaries.binary_util import BinaryUtil
from pants.pantsd.watchman import Watchman
from pants.util.memo import testable_memoized_property


class WatchmanLauncher(object):
  """An object that manages the configuration and lifecycle of Watchman."""

  @classmethod
  def create(cls, bootstrap_options):
    """
    :param Options bootstrap_options: The bootstrap options bag.
    """
    binary_util = BinaryUtil(
      bootstrap_options.binaries_baseurls,
      bootstrap_options.binaries_fetch_timeout_secs,
      bootstrap_options.pants_bootstrapdir,
      bootstrap_options.binaries_path_by_id
    )

    return WatchmanLauncher(
      binary_util,
      bootstrap_options.level,
      bootstrap_options.watchman_version,
      bootstrap_options.watchman_supportdir,
      bootstrap_options.watchman_startup_timeout,
      bootstrap_options.watchman_socket_timeout,
      bootstrap_options.watchman_socket_path,
      bootstrap_options.pants_subprocessdir
    )

  def __init__(self, binary_util, log_level, watchman_version, watchman_supportdir,
               startup_timeout, socket_timeout, socket_path_override=None, metadata_base_dir=None):
    """
    :param binary_util: The BinaryUtil subsystem instance for binary retrieval.
    :param log_level: The current log level of pants.
    :param watchman_version: The watchman binary version to retrieve using BinaryUtil.
    :param watchman_supportdir: The supportdir for BinaryUtil.
    :param socket_timeout: The watchman client socket timeout (in seconds).
    :param socket_path_override: The overridden target path of the watchman socket, if any.
    :param metadata_base_dir: The ProcessManager metadata base directory.
    """
    self._binary_util = binary_util
    self._watchman_version = watchman_version
    self._watchman_supportdir = watchman_supportdir
    self._startup_timeout = startup_timeout
    self._socket_timeout = socket_timeout
    self._socket_path_override = socket_path_override
    self._log_level = log_level
    self._logger = logging.getLogger(__name__)
    self._metadata_base_dir = metadata_base_dir

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
    return Watchman(
      watchman_binary,
      self._metadata_base_dir,
      self._convert_log_level(self._log_level),
      self._startup_timeout,
      self._socket_timeout,
      self._socket_path_override,
    )

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
