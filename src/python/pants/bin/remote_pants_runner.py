# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import signal
import sys
from contextlib import contextmanager

from pants.java.nailgun_client import NailgunClient
from pants.java.nailgun_protocol import NailgunProtocol
from pants.pantsd.process_manager import ProcessMetadataManager


class RemotePantsRunner(object):
  """A thin client variant of PantsRunner."""

  class PortNotFound(Exception): pass

  PANTS_COMMAND = 'pants'
  RECOVERABLE_EXCEPTIONS = (PortNotFound, NailgunClient.NailgunConnectionError)

  def __init__(self, exiter, args, env, process_metadata_dir=None,
               stdin=None, stdout=None, stderr=None):
    """
    :param Exiter exiter: The Exiter instance to use for this run.
    :param list args: The arguments (e.g. sys.argv) for this run.
    :param dict env: The environment (e.g. os.environ) for this run.
    :param str process_metadata_dir: The directory in which process metadata is kept.
    :param file stdin: The stream representing stdin.
    :param file stdout: The stream representing stdout.
    :param file stderr: The stream representing stderr.
    """
    self._exiter = exiter
    self._args = args
    self._env = env
    self._process_metadata_dir = process_metadata_dir
    self._stdin = stdin or sys.stdin
    self._stdout = stdout or sys.stdout
    self._stderr = stderr or sys.stderr
    self._port = self._retrieve_pailgun_port()
    if not self._port:
      raise self.PortNotFound('unable to locate pailgun port!')

  @staticmethod
  def _combine_dicts(*dicts):
    """Combine one or more dicts into a new, unified dict (dicts to the right take precedence)."""
    return {k: v for d in dicts for k, v in d.items()}

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

  def _retrieve_pailgun_port(self):
    return ProcessMetadataManager(
      self._process_metadata_dir).read_metadata_by_name('pantsd', 'socket_pailgun', int)

  def run(self, args=None):
    # Merge the nailgun TTY capability environment variables with the passed environment dict.
    ng_env = NailgunProtocol.isatty_to_env(self._stdin, self._stdout, self._stderr)
    modified_env = self._combine_dicts(self._env, ng_env)

    # Instantiate a NailgunClient.
    client = NailgunClient(port=self._port, ins=self._stdin, out=self._stdout, err=self._stderr)

    with self._trapped_control_c(client):
      # Execute the command on the pailgun.
      result = client.execute(self.PANTS_COMMAND, *self._args, **modified_env)

    # Exit.
    self._exiter.exit(result)
