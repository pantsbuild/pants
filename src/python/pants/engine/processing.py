# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty
from multiprocessing import Process, Queue
from Queue import Queue as ThreadQueue

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from pants.engine.scheduler import StepRequest


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


def _stateful_thread_pool_loop(send_queue, recv_queue, initializer, function):
  """A top-level function implementing the loop for a StatefulPool."""
  states = initializer()

  while True:
    item = recv_queue.get(block=True)
    if item is None:
      # Shutdown requested.
      return

    # Execute the function, and return the result.
    if isinstance(item, StepRequest):
      result = function(states, item)
    else:
      result = item() # Handle async cache fetching
    send_queue.put(result, block=True)


class StatefulPoolBase(object):
  """A Thread.Pool-alike with stateful workers running the same function.

  Note: there is no exception handling wrapping the function, so it should handle its
  own exceptions and return a failure result if need be.

  :param pool_size: The number of workers.
  :param initializer: To provide the initial states for each worker.
  :param function: The function which will be executed for each input object, and receive
    the worker's state and the current input. Should return the value that will be returned
    to the calling thread.
  """

  @abstractproperty
  def _pool_constructor(self):
    """Allow the child class to define the type of pool.

    The pool must be concurrent.futures like
    """

  def __init__(self, pool_size, initializer, function):
    super(StatefulPoolBase, self).__init__()

    self._pool_size = pool_size

    self._send = Queue()
    self._recv = Queue()

    self._executor = self._pool_constructor(max_workers=self._pool_size)
    self._fn_args = (self._recv, self._send, initializer, function)

  def start(self):
    for _ in range(self._pool_size):
      self._executor.submit(_stateful_pool_loop, *self._fn_args)

  def submit(self, item):
    if item is None:
      raise ValueError('Only non-None inputs are supported.')
    self._send.put(item, block=True)

  def await_one_result(self):
    return self._recv.get(block=True)

  def close(self):
    for _ in range(self._pool_size):
      self._send.put(None, block=True)
    self._executor.shutdown()


class StatefulThreadPoolBase(StatefulPoolBase):
  """A Thread.Pool-alike with stateful workers running the same function.

  Note: there is no exception handling wrapping the function, so it should handle its
  own exceptions and return a failure result if need be.

  :param pool_size: The number of workers.
  :param initializer: To provide the initial states for each worker.
  :param function: The function which will be executed for each input object, and receive
    the worker's state and the current input. Should return the value that will be returned
    to the calling thread.
  """

  @property
  def _pool_constructor(self):
    return ThreadPoolExecutor

  def __init__(self, pool_size, initializer, function):
    self._pool_size = pool_size

    self._send = ThreadQueue()
    self._recv = ThreadQueue()

    self._executor = self._pool_constructor(max_workers=self._pool_size)
    self._fn_args = (self._recv, self._send, initializer, function)

  def start(self):
    for _ in range(self._pool_size):
      self._executor.submit(_stateful_thread_pool_loop, *self._fn_args)


class StatefulProcessPoolBase(StatefulPoolBase):
  """A multiprocessing.Pool-alike with stateful workers running the same function.

  Note: there is no exception handling wrapping the function, so it should handle its
  own exceptions and return a failure result if need be.

  :param pool_size: The number of workers.
  :param initializer: To provide the initial states for each worker.
  :param function: The function which will be executed for each input object, and receive
    the worker's state and the current input. Should return the value that will be returned
    to the calling thread.
  """

  @property
  def _pool_constructor(self):
    return ProcessPoolExecutor

  def __init__(self, pool_size, initializer, function):
    # NOTE: It's unclear why but subclassing StatefulBasePool similar to StatefulThreadPool
    # causes the process to lock up. For now I am leaving the existing implementation as is.
    super(StatefulProcessPoolBase, self).__init__(pool_size, initializer, function)

    self._pool_size = pool_size

    self._send = Queue()
    self._recv = Queue()

    self._processes = [Process(target=_stateful_pool_loop,
                               args=(self._recv, self._send, initializer, function))
                       for _ in range(pool_size)]

  def start(self):
    for process in self._processes:
      process.start()

  def close(self):
    for _ in self._processes:
      self._send.put(None, block=False)
    for process in self._processes:
      process.join(10)
