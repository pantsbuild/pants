# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import logging
import os
from collections import namedtuple

from pants.pantsd.process_manager import ProcessManager
from pants.pantsd.watchman_client import StreamableWatchmanClient
from pants.util.dirutil import safe_mkdir


class Watchman(ProcessManager):
  """Watchman process manager and helper class."""

  SOCKET_TIMEOUT_SECONDS = 1

  EventHandler = namedtuple('EventHandler', ['name', 'metadata', 'callback'])

  def __init__(self, work_dir, log_level=1, watchman_path=None):
    super(Watchman, self).__init__(name='watchman', process_name='watchman', socket_type=str)
    self._logger = logging.getLogger(__name__)
    self._log_level = log_level
    self.watchman_path = self._resolve_watchman_path(watchman_path)

    # TODO(kwlzn): should these live in .pids or .pants.d? i.e. should watchman survive clean-all?
    self._work_dir = os.path.join(work_dir, self.name)
    self._state_file = os.path.join(self._work_dir, '{}.state'.format(self.name))
    self._log_file = os.path.join(self._work_dir, '{}.log'.format(self.name))
    self._sock_file = os.path.join(self._work_dir, '{}.sock'.format(self.name))

    self._watchman_client = None

  @property
  def client(self):
    if not self._watchman_client:
      self._watchman_client = self._make_client()
    return self._watchman_client

  def _make_client(self, timeout=SOCKET_TIMEOUT_SECONDS):
    """Create a new watchman client using the BSER protocol over a UNIX socket."""
    return StreamableWatchmanClient(sockpath=self.socket, transport='local', timeout=timeout)

  def _is_valid_executable(self, binary_path):
    return os.path.isfile(binary_path) and os.access(binary_path, os.X_OK)

  def _find_watchman_in_path(self):
    for path in os.environ['PATH'].split(os.pathsep):
      binary_path = os.path.join(path, self.process_name)
      if self._is_valid_executable(binary_path):
        return binary_path

  def _resolve_watchman_path(self, watchman_path=None):
    if watchman_path is not None:
      if not self._is_valid_executable(watchman_path):
        raise self.ExecutionError('invalid watchman binary at {}!'.format(watchman_path))
    else:
      watchman_path = self._find_watchman_in_path()
      if not watchman_path:
        raise self.ExecutionError('could not locate watchman in $PATH!')

    return os.path.abspath(watchman_path)

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

  def _parse_pid_from_output(self, output):
    try:
      # Parse the watchman pidfile from the cli output (in JSON).
      return json.loads(output)['pid']
    except ValueError:
      # JSON parse failure.
      self._logger.critical('invalid output from watchman!\n{output!s}'.format(output=output))
      raise self.InvalidCommandOutput(output)
    except KeyError:
      # Key access error on 'pid' - bad output from watchman.
      self._logger.critical('no pid from watchman!')
      raise self.InvalidCommandOutput(output)

  def launch(self):
    """Launch and synchronously write metadata.

    This is possible due to watchman's built-in async server startup - no double-forking required.
    """
    cmd = self._construct_cmd((self.watchman_path, 'get-pid'),
                              state_file=self._state_file,
                              sock_file=self._sock_file,
                              log_file=self._log_file,
                              log_level=str(self._log_level))
    self._logger.debug('watchman cmd is: {}'.format(' '.join(cmd)))
    self._maybe_init_metadata()

    # Spawn the watchman server (if not already running). Raise ExecutionError on failure.
    output = self.get_subprocess_output(cmd)

    # Parse the watchman PID from the cli output.
    pid = self._parse_pid_from_output(output)

    # Write the process metadata to disk.
    self.write_pid(pid)
    self.write_socket(self._sock_file)

  def watch_project(self, path):
    """Issues the watch-project command to watchman to begin watching the buildroot.

       :param string path: the path to the watchman project root/pants build root.
    """
    # TODO(kwlzn): this can fail with SocketTimeout - add retry.
    return self.client.query('watch-project', os.path.realpath(path))

  def subscribed(self, build_root, handlers):
    """Bulk subscribe generator for StreamableWatchmanClient.

       :param str build_root: the build_root for all subscriptions.
       :param iterable handlers: a sequence of Watchman.EventHandler namedtuple objects.
       :yields: a stream of tuples in the form (subscription_name: str, subscription_event: dict).
    """
    command_list = [['subscribe',
                     build_root,
                     handler.name,
                     handler.metadata] for handler in handlers]

    self._logger.debug('watchman command_list is: {}'.format(command_list))

    for event in self.client.stream_query(command_list):
      if event is None:
        yield None, None
      elif 'subscribe' in event:
        self._logger.info('confirmed watchman subscription: {}'.format(event))
        yield None, None
      elif 'subscription' in event:
        yield event.get('subscription'), event
      else:
        self._logger.warning('encountered non-subscription event: {}'.format(event))
