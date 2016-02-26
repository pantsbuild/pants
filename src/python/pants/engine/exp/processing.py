# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from multiprocessing import Process, Queue


def _stateful_pool_loop(send_queue, recv_queue, function, state):
  """A top-level function implementing the loop for a StatefulPool."""
  while True:
    item = recv_queue.get(block=True)
    if item is None:
      # Shutdown requested.
      return
    # Execute the function, and return the result.
    result = function(state, item)
    send_queue.put(result, block=True)


class StatefulPool(object):
  """A multiprocessing.Pool-alike with stateful workers running the same function.
  
  Note: there is no exception handling wrapping the function, so it should handle its
  own exceptions and return a failure result if need be.

  :param pool_size: The number of workers.
  :param function: The function which will be executed for each input object, and receive
    the worker's state and the current input. Should return the value that will be returned
    to the calling thread.
  :param initial_state: The initial state for each worker. Once the pool is started, the
    value of the state will diverge in each instance of the worker.
  """

  def __init__(self, pool_size, function, initial_state):
    super(StatefulPool, self).__init__()

    self._pool_size = pool_size

    self._send = Queue()
    self._recv = Queue()

    self._processes = [Process(target=_stateful_pool_loop,
                               args=(self._recv, self._send, function, initial_state))
                       for _ in range(pool_size)]

  def start(self):
    for process in self._processes:
      process.start()

  def submit(self, item):
    if item is None:
      raise ValueError('Only non-None inputs are supported.')
    self._send.put(item, block=True)

  def await_one_result(self):
    return self._recv.get(block=True)

  def close(self):
    for _ in self._processes:
      self._send.put(None, block=False)
    for process in self._processes:
      process.join(10)
