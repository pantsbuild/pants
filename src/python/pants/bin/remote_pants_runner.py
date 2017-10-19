# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import signal
import sys
from contextlib import contextmanager

from pants.bin.engine_initializer import EngineInitializer
from pants.java.nailgun_client import NailgunClient
from pants.java.nailgun_protocol import NailgunProtocol
from pants.pantsd.pants_daemon_launcher import PantsDaemonLauncher
from pants.util.collections import combined_dict


logger = logging.getLogger(__name__)


class RemotePantsRunner(object):
  """A thin client variant of PantsRunner."""

  class Fallback(Exception):
    """Raised when fallback to an alternate execution mode is requested."""

  class PortNotFound(Exception):
    """Raised when the pailgun port can't be found."""

  PANTS_COMMAND = 'pants'
  RECOVERABLE_EXCEPTIONS = (PortNotFound, NailgunClient.NailgunConnectionError)

  def __init__(self, exiter, args, env, process_metadata_dir,
               bootstrap_options, stdin=None, stdout=None, stderr=None):
    """
    :param Exiter exiter: The Exiter instance to use for this run.
    :param list args: The arguments (e.g. sys.argv) for this run.
    :param dict env: The environment (e.g. os.environ) for this run.
    :param str process_metadata_dir: The directory in which process metadata is kept.
    :param Options bootstrap_options: The Options bag containing the bootstrap options.
    :param file stdin: The stream representing stdin.
    :param file stdout: The stream representing stdout.
    :param file stderr: The stream representing stderr.
    """
    self._exiter = exiter
    self._args = args
    self._env = env
    self._process_metadata_dir = process_metadata_dir
    self._bootstrap_options = bootstrap_options
    self._stdin = stdin or sys.stdin
    self._stdout = stdout or sys.stdout
    self._stderr = stderr or sys.stderr
    self._launcher = PantsDaemonLauncher(self._bootstrap_options, EngineInitializer)

  @contextmanager
  def _trapped_control_c(self, client):
    """A contextmanager that overrides the SIGINT (control-c) handler and handles it remotely."""
    def handle_control_c(signum, frame):
      client.send_control_c()

    existing_sigint_handler = signal.signal(signal.SIGINT, handle_control_c)
    signal.siginterrupt(signal.SIGINT, False)  # Retry interrupted system calls.
    try:
      yield
    finally:
      signal.signal(signal.SIGINT, existing_sigint_handler)

  def _setup_logging(self):
    """Sets up basic stdio logging for the thin client."""
    log_level = logging.getLevelName(self._bootstrap_options.level.upper())

    formatter = logging.Formatter('%(levelname)s] %(message)s')
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.addHandler(handler)

  def _find_or_launch_pantsd(self):
    """Launches pantsd if configured to do so.

    :returns: The port pantsd can be found on.
    :rtype: int
    """
    return self._launcher.maybe_launch()

  def _connect_and_execute(self, port):
    # Merge the nailgun TTY capability environment variables with the passed environment dict.
    ng_env = NailgunProtocol.isatty_to_env(self._stdin, self._stdout, self._stderr)
    modified_env = combined_dict(self._env, ng_env)

    assert isinstance(port, int), 'port {} is not an integer!'.format(port)

    # Instantiate a NailgunClient.
    client = NailgunClient(port=port,
                           ins=self._stdin,
                           out=self._stdout,
                           err=self._stderr,
                           exit_on_broken_pipe=True)

    with self._trapped_control_c(client):
      # Execute the command on the pailgun.
      result = client.execute(self.PANTS_COMMAND, *self._args, **modified_env)

    # Exit.
    self._exiter.exit(result)

  def run(self, args=None):
    self._setup_logging()
    port = self._find_or_launch_pantsd()

    logger.debug('connecting to pailgun on port {}'.format(port))
    try:
      self._connect_and_execute(port)
    except self.RECOVERABLE_EXCEPTIONS as e:
      raise self.Fallback(e)
