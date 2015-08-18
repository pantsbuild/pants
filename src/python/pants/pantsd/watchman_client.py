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

  def stream_query(self, commands):
    """A generator of watchman events that allows queries to be pipelined and multiplexed. This
       continuously yields unilateral events and subscribe events, or None until an error condition
       or non-unilateral event (aside from subscribe) is received, at which point the generator
       ceases.

       The generator will yield None on socket timeouts unless the client's timeout has been set to
       None, in which case it will block indefinitely waiting on responses.

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
          raise pywatchman.WatchmanError('error from watchman: {}'.format(result['error']))
        elif self.isUnilateralResponse(result) or 'subscribe' in result:
          yield result
        else:
          yield result
          break
