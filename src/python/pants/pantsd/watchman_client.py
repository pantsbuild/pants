# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import deque

import pywatchman


# TODO(kwlzn): upstream this in pywatchman.
class StreamableWatchmanClient(pywatchman.client):
  """A watchman client subclass that provides for interruptable unilateral queries."""

  # Ensure 'subscribe' responses are tagged as unilateral in support of pipelining.
  unilateral = ['log', 'subscription', 'subscribe']

  def stream_query(self, commands):
    """A streaming, bulk form of pywatchman.client.query(). This will pipeline a set of queries to
       watchman over the UNIX socket and multiplex events in a continously yielding generator (with
       per-event keying possible off of subscription name). Note that batch-mode operation (e.g.
       passing a sequence of commands) is generally only suitable for the 'subscription' command.

       For unilateral commands with a timeout, this is also non-blocking such that it is possible
       to gracefully interrupt the execution via the caller whether we have a result or not (by
       continuously yielding runtime context). The caller is expected to handle empty yields by
       None-checking the return value in the iterating loop. To disable this behavior, you can
       pass an __init__(timeout=None) parameter to block indefinitely on response.

       :param iterable commands: An iterable of commands to send to watchman - e.g. one or more
                                 subscribe commands.
    """
    # The CLI transport does not support pipelining.
    if self.transport is pywatchman.CLIProcessTransport:
      raise NotImplementedError()

    cmd_buf = deque(command for command in reversed(commands))
    self._connect()

    while 1:
      # Interleave sends and receives to avoid bi-directional communication issues.
      if cmd_buf:
        item = cmd_buf.pop()
        try:
          self.sendConn.send(item)
        except pywatchman.SocketTimeout:
          cmd_buf.append(item)
          yield

      try:
        result = self.recvConn.receive()
      except pywatchman.SocketTimeout:
        # Socket timeout - yield runtime context.
        yield
      else:
        if 'error' in result:
          raise pywatchman.WatchmanError('error from watchman: {}'.format())
        elif self.isUnilateralResponse(result):
          yield result
        else:
          break
