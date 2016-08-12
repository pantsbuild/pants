# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import logging
import multiprocessing
import traceback
from abc import abstractmethod
from collections import OrderedDict
from Queue import Queue

from concurrent.futures import ThreadPoolExecutor

from pants.base.exceptions import TaskError
from pants.engine.nodes import Return, Throw
from pants.engine.objects import SerializationError
from pants.engine.processing import StatefulPool
from pants.engine.storage import Cache, Storage
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


try:
  import cPickle as pickle
except ImportError:
  import pickle

logger = logging.getLogger(__name__)


class InFlightException(Exception):
  pass


class StepBatchException(Exception):
  pass


class Engine(AbstractClass):
  """An engine for running a pants command line."""

  class Result(datatype('Result', ['error', 'root_products'])):
    """Represents the result of a single engine run."""

    @classmethod
    def finished(cls, root_products):
      """Create a success or partial success result from a finished run.

      Runs can either finish with no errors, satisfying all promises, or they can partially finish
      if run in fail-slow mode producing as many products as possible.
      :param root_products: Mapping of root SelectNodes to their State values.
      :rtype: `Engine.Result`
      """
      return cls(error=None, root_products=root_products)

    @classmethod
    def failure(cls, error):
      """Create a failure result.

      A failure result represent a run with a fatal error.  It presents the error but no
      products.

      :param error: The execution error encountered.
      :type error: :class:`pants.base.exceptions.TaskError`
      :rtype: `Engine.Result`
      """
      return cls(error=error, root_products=None)

  def __init__(self, scheduler, storage=None, cache=None):
    """
    :param scheduler: The local scheduler for creating execution graphs.
    :type scheduler: :class:`pants.engine.scheduler.LocalScheduler`
    :param storage: The storage instance for serializables keyed by their hashes.
    :type storage: :class:`pants.engine.storage.Storage`
    :param cache: The cache instance for storing execution results, by default it uses the same
      Storage instance if not specified.
    :type cache: :class:`pants.engine.storage.Cache`
    """
    self._scheduler = scheduler
    self._storage = storage or Storage.create()
    self._cache = cache or Cache.create(storage)

  def execute(self, execution_request):
    """Executes the requested build.

    :param execution_request: The description of the goals to achieve.
    :type execution_request: :class:`ExecutionRequest`
    :returns: The result of the run.
    :rtype: :class:`Engine.Result`
    """
    try:
      self.reduce(execution_request)
      return self.Result.finished(self._scheduler.root_entries(execution_request))
    except TaskError as e:
      return self.Result.failure(e)

  def close(self):
    """Shutdown this engine instance, releasing resources it was using."""
    self._storage.close()
    self._cache.close()

  def cache_stats(self):
    """Returns cache stats for the engine."""
    return self._cache.get_stats()

  def _maybe_cache_get(self, node_entry, runnable):
    """If caching is enabled for the given Entry, create a key and perform a lookup.

    The sole purpose of a keyed request is to get a stable cache key, so we can sort
    keyed_request.dependencies by keys as opposed to requiring dep nodes to support compare.

    :returns: A tuple of a key and result, either of which may be None.
    """
    if not node_entry.node.is_cacheable:
      return None, None
    return self._cache.get(runnable)

  def _maybe_cache_put(self, key, result):
    if key is not None:
      self._cache.put(key, result)

  @abstractmethod
  def reduce(self, execution_request):
    """Reduce the given execution graph returning its root products.

    :param execution_request: The description of the goals to achieve.
    :type execution_request: :class:`ExecutionRequest`
    :returns: The root products promised by the execution graph.
    :rtype: dict of (:class:`Promise`, product)
    """


class LocalSerialEngine(Engine):
  """An engine that runs tasks locally and serially in-process."""

  def reduce(self, execution_request):
    generator = self._scheduler.schedule(execution_request)
    for runnable_batch in generator:
      completed = []
      for entry, runnable in runnable_batch:
        key, result = self._maybe_cache_get(entry, runnable)
        if result is None:
          try:
            result = Return(runnable.func(*runnable.args))
            self._maybe_cache_put(key, result)
          except Exception as e:
            result = Throw(e)
        completed.append((entry, result))
      generator.send(completed)


def _try_pickle(obj):
  try:
    pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
  except Exception as e:
    # Unfortunately, pickle can raise things other than PickleError instances.  For example it
    # will raise ValueError when handed a lambda; so we handle the otherwise overly-broad
    # `Exception` type here.
    raise SerializationError('Failed to pickle {}: {}'.format(obj, e))


class ConcurrentEngine(Engine):
  def reduce(self, execution_request):
    """The main reduction loop."""
    # 1. Whenever we don't have enough work to saturate the pool, request more.
    # 2. Whenever the pool is not saturated, submit currently pending work.

    # Step instances which have not been submitted yet.
    pending_submission = OrderedDict()
    in_flight = dict()  # Dict from step id to a Promise for Steps that have been submitted.

    def submit_until(completed, n):
      submitted, local_completed = self._submit_until(pending_submission, in_flight, n)
      completed.extend(local_completed)
      return submitted

    def await_one(completed):
      completed.append(self._await_one(in_flight))

    generator = self._scheduler.schedule(execution_request)
    for step_batch in generator:
      completed = []
      if not step_batch:
        # A batch should only be empty if all dependency work is currently blocked/running.
        if not in_flight and not pending_submission:
          raise StepBatchException(
            'Scheduler provided an empty batch while no work is in progress!')
      else:
        # Submit and wait for work for as long as we're able to keep the pool saturated.
        pending_submission.update(step_batch)
        while submit_until(completed, self._pool_size) > 0:
          await_one(completed)
      # Await at least one entry per scheduling loop.
      submit_until(completed, 0)
      if in_flight:
        await_one(completed)

      # Indicate which items have completed.
      generator.send(completed)

    if pending_submission or in_flight:
      raise AssertionError('Engine loop completed with items: {}, {}'.format(pending_submission, in_flight))

  @abstractmethod
  def _submit_until(self, pending_submission, in_flight, n):
    """Submit pending while there's capacity, and more than `n` items in pending_submission.

    Returns a tuple of entries running in the background, and entries that completed immediately.
    """

  @abstractmethod
  def _await_one(self, in_flight):
    """Await one completed step, remove it from in_flight, and return it."""


class ThreadHybridEngine(ConcurrentEngine):
  """An engine that runs locally but allows nodes to be optionally run concurrently.

  The decision to run concurrently or in serial is determined by _is_async_node.
  For IO bound nodes we will run concurrently using threads.
  """

  def __init__(self, scheduler, storage, cache=None, threaded_node_types=tuple(),
               pool_size=None, debug=True):
    """
    :param scheduler: The local scheduler for creating execution graphs.
    :type scheduler: :class:`pants.engine.scheduler.LocalScheduler`
    :param storage: The storage instance for serializables keyed by their hashes.
    :type storage: :class:`pants.engine.storage.Storage`
    :param cache: The cache instance for storing execution results, by default it uses the same
      Storage instance if not specified.
    :type cache: :class:`pants.engine.storage.Cache`
    :param tuple threaded_node_types: Node types that will be processed using the thread pool.
    :param int pool_size: The number of worker processes to use; by default 2 processes per core will
                          be used.
    :param bool debug: `True` to turn on pickling error debug mode (slower); True by default.
    """
    super(ThreadHybridEngine, self).__init__(scheduler, storage, cache)
    self._pool_size = pool_size if pool_size and pool_size > 0 else 2 * multiprocessing.cpu_count()

    self._pending = set()  # Keep track of futures so we can cleanup at the end.
    self._processed_queue = Queue()
    self._async_nodes = threaded_node_types
    self._node_builder = scheduler.node_builder
    self._state = (self._node_builder, storage)
    self._pool = ThreadPoolExecutor(max_workers=self._pool_size)
    self._debug = debug

  def _is_async_node(self, node):
    """Override default behavior and handle specific nodes asynchronously."""
    return isinstance(node, self._async_nodes)

  def _maybe_cache_step(self, step_request):
    if step_request.node.is_cacheable:
      return step_request.step_id, self._cache.get(step_request)
    else:
      return step_request.step_id, None

  def _execute_step(self, step, runnable):
    """A function to help support local step execution.

    :param step: Step to be executed.
    """
    key, result = self._maybe_cache_get(step, runnable)
    if result is None:
      try:
        result = Return(runnable.func(*runnable.args))
        self._maybe_cache_put(key, result)
      except Exception as e:
        result = Throw(e)
    return step, result

  def _processed_node_callback(self, finished_future):
    self._processed_queue.put(finished_future)
    self._pending.remove(finished_future)

  def _submit_until(self, pending_submission, in_flight, n):
    """Submit pending while there's capacity, and more than `n` items in pending_submission."""
    to_submit = min(len(pending_submission) - n, self._pool_size - len(in_flight))
    submitted = 0
    completed = []
    for _ in range(to_submit):
      step, runnable = pending_submission.popitem(last=False)
      if self._is_async_node(step.node):
        # Run in a future.
        if step in in_flight:
          raise InFlightException('{} is already in_flight!'.format(step))

        future = self._pool.submit(functools.partial(self._execute_step, step, runnable))
        in_flight[step] = future
        self._pending.add(future)
        future.add_done_callback(self._processed_node_callback)

        submitted += 1

      else:
        # Run inline.
        completed.append(self._execute_step(step, runnable))

    return submitted, completed

  def _await_one(self, in_flight):
    """Await one completed step, and remove it from in_flight."""
    if not in_flight:
      raise InFlightException('Awaited an empty pool!')

    entry, result = self._processed_queue.get().result()
    if isinstance(result, Exception):
      raise result
    in_flight.pop(entry)
    return entry, result

  def close(self):
    """Cleanup thread pool."""
    for f in self._pending:
      f.cancel()
    self._pool.shutdown()  # Wait for pool to cleanup before we cleanup storage.
    super(ThreadHybridEngine, self).close()


def _execute_step(debug, process_state, step):
  """A picklable top-level function to help support local multiprocessing uses.
  Executes the Step for the given node builder and storage, and returns a tuple of step id and
  result or exception. Since step execution is only on cache misses, this also saves result
  to the cache.
  """
  storage, cache = process_state
  step_id, cache_key, runnable = step


  # TODO! need to move back to storing all content and then retrieving it from Storage here.
  def execute():
    try:
      result = Return(runnable.func(*runnable.args))
      if debug:
        _try_pickle(result)
      if cache_key is not None:
        cache.put(cache_key, result)
    except Exception as e:
      result = Throw(e)
    return result

  try:
    return step_id, execute()
  except Exception as e:
    # Trap any exception raised by the execution node that bubbles up, and
    # pass this back to our main thread for handling.
    logger.warn(traceback.format_exc())
    return step_id, e


def _process_initializer(storage):
  """Another picklable top-level function that provides multi-processes' initial states.

  States are returned as a tuple. States are `Closable` so they can be cleaned up once
  processes are done.
  """
  storage = Storage.clone(storage)
  return (storage, Cache.create(storage=storage))


class LocalMultiprocessEngine(ConcurrentEngine):
  """An engine that runs tasks locally and in parallel when possible using a process pool."""

  def __init__(self, scheduler, storage=None, cache=None, pool_size=None, debug=True):
    """
    :param scheduler: The local scheduler for creating execution graphs.
    :type scheduler: :class:`pants.engine.scheduler.LocalScheduler`
    :param storage: The storage instance for serializables keyed by their hashes.
    :type storage: :class:`pants.engine.storage.Storage`
    :param cache: The cache instance for storing execution results, by default it uses the same
      Storage instance if not specified.
    :type cache: :class:`pants.engine.storage.Cache`
    :param int pool_size: The number of worker processes to use; by default 2 processes per core will
                          be used.
    :param bool debug: `True` to turn on pickling error debug mode (slower); True by default.
    """
    # This is the only place where non in-memory storage is needed, create one if not specified.
    storage = storage or Storage.create(in_memory=False)
    super(LocalMultiprocessEngine, self).__init__(scheduler, storage, cache)
    self._pool_size = pool_size if pool_size and pool_size > 0 else 2 * multiprocessing.cpu_count()

    execute_step = functools.partial(_execute_step, debug)

    self._processed_queue = Queue()
    self.node_builder = scheduler.node_builder
    process_initializer = functools.partial(_process_initializer, self._storage)
    self._pool = StatefulPool(self._pool_size, process_initializer, execute_step)
    self._debug = debug
    self._pool.start()

  def _submit(self, step_id, cache_key, runnable):
    entry = (step_id, cache_key, runnable)
    _try_pickle(entry)
    self._pool.submit(entry)

  def close(self):
    self._pool.close()

  def _submit_until(self, pending_submission, in_flight, n):
    """Submit pending while there's capacity, and more than `n` items pending_submission."""
    to_submit = min(len(pending_submission) - n, self._pool_size - len(in_flight))
    submitted = 0
    completed = []
    for _ in range(to_submit):
      step, runnable = pending_submission.popitem(last=False)
      if step in in_flight:
        raise InFlightException('{} is already in_flight!'.format(step))

      cache_key, result = self._maybe_cache_get(step, runnable)
      if result is not None:
        # Skip in_flight on cache hit.
        completed.append((step, result))
      else:
        step_id = id(step)
        in_flight[step_id] = step
        self._submit(step_id, cache_key, runnable)
        submitted += 1

    return submitted, completed

  def _await_one(self, in_flight):
    """Await one completed step, and remove it from in_flight."""
    if not in_flight:
      raise InFlightException('Awaited an empty pool!')
    step_id, result = self._pool.await_one_result()
    if isinstance(result, Exception):
      raise result
    if step_id not in in_flight:
      raise InFlightException(
        'Received unexpected work from the Executor: {} vs {}'.format(step_id, in_flight.keys()))
    return in_flight.pop(step_id), result
