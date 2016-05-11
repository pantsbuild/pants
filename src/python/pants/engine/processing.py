# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from multiprocessing import Process, Queue
from threading import Thread
from time import time


def _stateful_pool_loop(send_queue, recv_queue, initializer, function):
  """A top-level function implementing the loop for a StatefulPool."""
  states = initializer()

  try:
    while True:
      item = recv_queue.get(block=True)
      if item is None:
        # Shutdown requested.
        return
      # Execute the function, and return the result.
      result = function(states, item)
      send_queue.put(result, block=True)
  finally:
    for state in states:
      state.close()

class StatefulThreadPool(object):
  """A multiprocessing.Pool-alike with stateful workers running the same function.

  Note: there is no exception handling wrapping the function, so it should handle its
  own exceptions and return a failure result if need be.

  :param pool_size: The number of workers.
  :param initializer: To provide the initial states for each worker.
  :param function: The function which will be executed for each input object, and receive
    the worker's state and the current input. Should return the value that will be returned
    to the calling thread.
  """

  def __init__(self, pool_size, initializer, function):
    super(StatefulThreadPool, self).__init__()

    self._pool_size = pool_size

    self._send = Queue()
    self._recv = Queue()

    self._threads = [Thread(target=_stateful_pool_loop,
                            name="processing-pool-{}".format(i),
                            args=(self._recv, self._send, initializer, function))
                       for i in range(pool_size)]

  def start(self):
    for process in self._threads:
      process.start()

  def submit(self, item):
    if item is None:
      raise ValueError('Only non-None inputs are supported.')
    self._send.put(item, block=True)

  def await_one_result(self):
    return self._recv.get(block=True)

  def close(self):
    for _ in self._threads:
      self._send.put(None, block=False)
    deadline = 10 + time()
    print('got to close. Yay!')
    for thread in self._threads:
      thread.join(deadline - time())
      if thread.is_alive():
        print('failed to terminate thread.')

class StatefulPool(object):
  """A multiprocessing.Pool-alike with stateful workers running the same function.

  Note: there is no exception handling wrapping the function, so it should handle its
  own exceptions and return a failure result if need be.

  :param pool_size: The number of workers.
  :param initializer: To provide the initial states for each worker.
  :param function: The function which will be executed for each input object, and receive
    the worker's state and the current input. Should return the value that will be returned
    to the calling thread.
  """

  def __init__(self, pool_size, initializer, function):
    super(StatefulPool, self).__init__()

    self._pool_size = pool_size

    self._send = Queue()
    self._recv = Queue()

    self._processes = [Process(target=_stateful_pool_loop,
                               args=(self._recv, self._send, initializer, function))
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
