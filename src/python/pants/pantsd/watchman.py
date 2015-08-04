# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import logging
import os
import threading

from pants.base.build_environment import get_buildroot
from pants.pantsd.process_manager import ProcessManager
from pants.util.dirutil import safe_mkdir, touch


class Watchman(ProcessManager):
  """Watchman process manager."""

  def __init__(self, options):
    ProcessManager.__init__(self, name='watchman', process_name='watchman', socket_type=str)
    self._logger = logging.getLogger(__name__)
    self.options = options
    self.watchman_path = self.options.watchman_path or self._find_watchman_in_path()

    # TODO: should these live in .pids or .pants.d? i.e. should watchman survive clean-all?
    self._work_dir = os.path.join(get_buildroot(), '.pants.d', self.name)
    self._state_file = os.path.join(self._work_dir, '{}.state'.format(self.name))
    self._log_file = os.path.join(self._work_dir, '{}.log'.format(self.name))
    self._sock_file = os.path.join(self._work_dir, '{}.sock'.format(self.name))

  def _find_watchman_in_path(self):
    for path in os.environ['PATH'].split(os.pathsep):
      binary_path = os.path.join(path, self.process_name)
      if os.path.exists(binary_path) and os.access(binary_path, os.X_OK):
        return binary_path

  def _maybe_init_metadata(self):
    safe_mkdir(self._work_dir)
    # Initialize watchman with an empty, but valid statefile so it doesn't complain on startup.
    self._write_file(self._state_file, '{}')

  def _construct_cmd(self, cmd_parts, state_file, sock_file, log_file, log_level):
    return [part for part in cmd_parts] + ['--no-save-state',
                                           '--statefile={}'.format(state_file),
                                           '--sockname={}'.format(sock_file),
                                           '--logfile={}'.format(log_file),
                                           '--log-level', log_level]

  def launch(self):
    """Launch and synchronously write metadata. This is possible due to watchman's built-in async
       server startup - no double-forking required."""
    if not self.watchman_path:
      raise self.ExecutionError('watchman could not be located!')

    cmd = self._construct_cmd((self.watchman_path, 'get-pid'),
                              state_file=self._state_file,
                              sock_file=self._sock_file,
                              log_file=self._log_file,
                              log_level=str(self.options.log_level))
    self._logger.debug('watchman cmd is: {}'.format(' '.join(cmd)))
    self._maybe_init_metadata()

    # Spawn the watchman server (if not already running). Raise ExecutionError on failure.
    output = self.get_subprocess_output(cmd)

    try:
      # Parse the watchman pidfile from the cli output (in JSON).
      pid = json.loads(output)['pid']
    except ValueError:
      # JSON parse failure.
      self._logger.critical('invalid output from watchman!\n{output!s}'.format(output=output))
      raise self.InvalidCommandOutput(output)
    except KeyError:
      # Key access error on 'pid' - bad output from watchman.
      self._logger.critical('no pid from watchman!')
      raise self.InvalidCommandOutput(output)

    # Write the process metadata to disk.
    self.write_pid(pid)
    self.write_socket(self._sock_file)
