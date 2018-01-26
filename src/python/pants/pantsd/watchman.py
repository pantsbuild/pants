# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import json
import logging
import os
from collections import namedtuple

from pants.pantsd.process_manager import ProcessManager
from pants.pantsd.watchman_client import StreamableWatchmanClient
from pants.util.dirutil import safe_file_dump, safe_mkdir
from pants.util.retry import retry_on_exception


class Watchman(ProcessManager):
  """Watchman process manager and helper class."""

  class WatchmanCrash(Exception):
    """Raised when Watchman crashes."""

  STARTUP_TIMEOUT_SECONDS = 30.0
  SOCKET_TIMEOUT_SECONDS = 5.0

  EventHandler = namedtuple('EventHandler', ['name', 'metadata', 'callback'])

  def __init__(self, watchman_path, metadata_base_dir, log_level='1', startup_timeout=STARTUP_TIMEOUT_SECONDS,
               timeout=SOCKET_TIMEOUT_SECONDS, socket_path_override=None):
    """
    :param str watchman_path: The path to the watchman binary.
    :param str metadata_base_dir: The metadata base dir for `ProcessMetadataManager`.
    :param float startup_timeout: The timeout for the initial `watch-project` query (in seconds).
    :param float timeout: The watchman socket timeout for all subsequent queries (in seconds).
    :param str log_level: The watchman log level. Watchman has 3 log levels: '0' for no logging,
                          '1' for standard logging and '2' for verbose logging.
    :param str socket_path_override: The overridden target path of the watchman socket, if any.
    """
    super(Watchman, self).__init__(name='watchman',
                                   process_name='watchman',
                                   socket_type=str,
                                   metadata_base_dir=metadata_base_dir)
    self._watchman_path = self._normalize_watchman_path(watchman_path)
    self._watchman_work_dir = os.path.join(metadata_base_dir, self.name)
    self._log_level = log_level
    self._startup_timeout = startup_timeout
    self._timeout = timeout

    self._state_file = os.path.join(self._watchman_work_dir, '{}.state'.format(self.name))
    self._log_file = os.path.join(self._watchman_work_dir, '{}.log'.format(self.name))
    self._pid_file = os.path.join(self._watchman_work_dir, '{}.pid'.format(self.name))
    self._sock_file = socket_path_override or os.path.join(self._watchman_work_dir,
                                                           '{}.sock'.format(self.name))

    self._logger = logging.getLogger(__name__)
    self._watchman_client = None

  @property
  def client(self):
    if not self._watchman_client:
      self._watchman_client = self._make_client()
    return self._watchman_client

  def _make_client(self):
    """Create a new watchman client using the BSER protocol over a UNIX socket."""
    self._logger.debug('setting initial watchman timeout to %s', self._startup_timeout)
    return StreamableWatchmanClient(sockpath=self.socket,
                                    transport='local',
                                    timeout=self._startup_timeout)

  def _is_valid_executable(self, binary_path):
    return os.path.isfile(binary_path) and os.access(binary_path, os.X_OK)

  def _normalize_watchman_path(self, watchman_path):
    if not self._is_valid_executable(watchman_path):
      raise self.ExecutionError('invalid watchman binary at {}!'.format(watchman_path))
    return os.path.abspath(watchman_path)

  def _maybe_init_metadata(self):
    safe_mkdir(self._watchman_work_dir)
    # Initialize watchman with an empty, but valid statefile so it doesn't complain on startup.
    safe_file_dump(self._state_file, '{}')

  def _construct_cmd(self, cmd_parts, state_file, sock_file, pid_file, log_file, log_level):
    return [part for part in cmd_parts] + ['--no-save-state',
                                           '--no-site-spawner',
                                           '--statefile={}'.format(state_file),
                                           '--sockname={}'.format(sock_file),
                                           '--pidfile={}'.format(pid_file),
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
    cmd = self._construct_cmd((self._watchman_path, 'get-pid'),
                              state_file=self._state_file,
                              sock_file=self._sock_file,
                              pid_file=self._pid_file,
                              log_file=self._log_file,
                              log_level=str(self._log_level))
    self._logger.debug('watchman cmd is: {}'.format(' '.join(cmd)))
    self._maybe_init_metadata()

    # Watchman is launched via its cli. By running the 'get-pid' command on the client we implicitly
    # launch the Watchman daemon. This approach is somewhat error-prone - in some cases the client
    # can successfully trigger the launch of the Watchman daemon, but fail to return successfully
    # for the 'get-pid' result due to server <-> daemon socket issues - these can look like:
    #
    #   2016-04-01T17:31:23,820: [cli] unable to talk to your watchman
    #                                  on .../watchman.sock! (Permission denied)
    #
    # This results in a subprocess execution failure and leaves us with no pid information to write
    # to the metadata directory - while in reality a Watchman daemon is actually running but now
    # untracked. To safeguard against this, we retry the (idempotent) 'get-pid' command a few times
    # to give the server-side socket setup a few chances to quiesce before potentially orphaning it.

    get_output = functools.partial(self.get_subprocess_output, cmd)
    output = retry_on_exception(get_output, 3, (self.ExecutionError,), lambda n: n * .5)

    # Parse the watchman PID from the cli output.
    pid = self._parse_pid_from_output(output)

    # Write the process metadata to disk.
    self.write_pid(pid)
    self.write_socket(self._sock_file)

  def _attempt_set_timeout(self, timeout):
    """Sets a timeout on the inner watchman client's socket."""
    try:
      self.client.setTimeout(timeout)
    except Exception:
      self._logger.debug('failed to set post-startup watchman timeout to %s', self._timeout)
    else:
      self._logger.debug('set post-startup watchman timeout to %s', self._timeout)

  def watch_project(self, path):
    """Issues the watch-project command to watchman to begin watching the buildroot.

    :param string path: the path to the watchman project root/pants build root.
    """
    # TODO(kwlzn): Add a client.query(timeout=X) param to the upstream pywatchman project.
    try:
      return self.client.query('watch-project', os.path.realpath(path))
    finally:
      self._attempt_set_timeout(self._timeout)

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

    try:
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
    except self.client.WatchmanError as e:
      raise self.WatchmanCrash(e)
