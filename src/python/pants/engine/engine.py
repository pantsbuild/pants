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
from Queue import Queue

from concurrent.futures import ThreadPoolExecutor
from twitter.common.collections.orderedset import OrderedSet

from pants.base.exceptions import TaskError
from pants.engine.objects import SerializationError
from pants.engine.processing import StatefulPool
from pants.engine.storage import Cache, Storage
from pants.util.memo import memoized_method
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

  def start(self):
    """Start up this engine instance, creating any resources it needs."""
    pass

  def close(self):
    """Shutdown this engine instance, releasing resources it was using."""
    self._storage.close()
    self._cache.close()

  def cache_stats(self):
    """Returns cache stats for the engine."""
    return self._cache.get_stats()

  @memoized_method
  def _should_cache(self, step_request):
    return step_request.node.is_cacheable

  def _maybe_cache_get(self, step_request):
    """If caching is enabled for the given StepRequest, create a keyed request and perform a lookup.

    The sole purpose of a keyed request is to get a stable cache key, so we can sort
    keyed_request.dependencies by keys as opposed to requiring dep nodes to support compare.

    :returns: A tuple of a keyed StepRequest and result, either of which may be None.
    """
    if not self._should_cache(step_request):
      return None, None
    keyed_request = self._storage.key_for_request(step_request)
    return keyed_request, self._cache.get(keyed_request)

  def _maybe_cache_put(self, keyed_request, step_result):
    if keyed_request is not None:
      self._cache.put(keyed_request, step_result)

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
    node_builder = self._scheduler.node_builder()
    for step_batch in self._scheduler.schedule(execution_request):
      for step, promise in step_batch:
        keyed_request, result = self._maybe_cache_get(step)
        if result is None:
          result = step(node_builder)
        self._maybe_cache_put(keyed_request, result)
        promise.success(result)


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
    pending_submission = OrderedSet()
    in_flight = dict()  # Dict from step id to a Promise for Steps that have been submitted.

    submit_until = functools.partial(self._submit_until, pending_submission, in_flight)
    await_one = functools.partial(self._await_one, in_flight)

    for step_batch in self._scheduler.schedule(execution_request):
      if not step_batch:
        # A batch should only be empty if all dependency work is currently blocked/running.
        if not in_flight and not pending_submission:
          raise StepBatchException(
            'Scheduler provided an empty batch while no work is in progress!')
      else:
        # Submit and wait for work for as long as we're able to keep the pool saturated.
        pending_submission.update(step_batch)
        while submit_until(self._pool_size) > 0:
          await_one()
      # Await at least one entry per scheduling loop.
      submit_until(0)
      if in_flight:
        await_one()

    # Consume all steps.
    while pending_submission or in_flight:
      submit_until(self._pool_size)
      await_one()

  @abstractmethod
  def _submit_until(self, pending_submission, in_flight, n):
    """Submit pending while there's capacity, and more than `n` items in pending_submission."""

  @abstractmethod
  def _await_one(self, in_flight):
    """Await one completed step, and remove it from in_flight."""


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
    self._node_builder = scheduler.node_builder()
    self._state = (self._node_builder, storage)
    self._pool = ThreadPoolExecutor(max_workers=self._pool_size)
    self._debug = debug

  def _is_async_node(self, node):
    """Override default behavior and handle specific nodes asynchronously."""
    return isinstance(node, self._async_nodes)

  def _maybe_cache_step(self, step_request):
    if self._should_cache(step_request):
      return step_request.step_id, self._cache.get(step_request)
    else:
      return step_request.step_id, None

  def _execute_step(self, step, cache_save=None, debug=False):
    """A function to help support local step execution.

    Executes the Step for the given node builder and storage, and returns a tuple of step id and
    result or exception.

    :param callable cache_save: Callable used to save cache results. If None skip saving to cache.
    :param bool debug: Determines if we do extra debugging steps.
    :param step: Step to be executed.
    """
    node_builder, storage = self._state
    step_id = step.step_id

    def execute():
      resolved_request = storage.resolve_request(step)
      result = resolved_request(node_builder)
      if debug:
        _try_pickle(result)
      if cache_save:
        keyed_result = storage.key_for_result(result)
        cache_save(step, keyed_result)
      return result

    try:
      return step_id, execute()
    except Exception as e:
      # Trap any exception raised by the execution node that bubbles up, and
      # pass this back to our main thread for handling.
      logger.warn(traceback.format_exc())
      return step_id, e

  def _deferred_step(self, step, should_cache):
    """Create a callable to process a step that is able to be passed to the thread pool

    Deferred method returns (step_id, result) so that it can be processed later.
    """
    cache_save = self._self._cache.put if should_cache else None
    return functools.partial(self._execute_step, step, cache_save = cache_save)

  def _deferred_cache(self, step):
    """Create a callable to fetch cache that is able to be passed to the thread pool

    Deferred method returns result without corresponding step id
    """
    def strip_step_id():
      # Discard keyed_result
      _, result = self._maybe_cache_get(step)
      resolved_result = None if result is None else self._storage.resolve_result(result)
      return step.step_id, resolved_result

    return strip_step_id

  def _processed_node_callback(self, finished_future):
    self._processed_queue.put(finished_future)
    self._pending.remove(finished_future)

  def _submit_until(self, pending_submission, in_flight, n):
    """Submit pending while there's capacity, and more than `n` items in pending_submission."""
    to_submit = min(len(pending_submission) - n, self._pool_size - len(in_flight))
    submitted = 0
    for _ in range(to_submit):
      step, promise = pending_submission.pop(last=False)
      if self._is_async_node(step.node):
        if step.step_id in in_flight:
          raise InFlightException('{} is already in_flight!'.format(step))

        in_flight[step.step_id] = promise

        should_cache = self._should_cache(step)
        futures = [self._pool.submit(self._deferred_step(step, should_cache))]

        if should_cache:
          cache_future = self._pool.submit(self.deferred_cache(step))
          futures.append(cache_future)

        for f in futures:
          self._pending.add(f)
          f.add_done_callback(self._processed_node_callback)

        submitted += 1

      else:
        keyed_request, result = self._maybe_cache_get(step)
        if result is None:
          result = step(self._node_builder)
          self._maybe_cache_put(keyed_request, result)
        promise.success(result)

    return submitted

  def _await_one(self, in_flight):
    """Await one completed step, and remove it from in_flight."""
    if not in_flight:
      raise InFlightException('Awaited an empty pool!')

    # Drop silently None results (these are cache misses).
    # Also drop steps that have already been handled.
    step_id = None
    result = None
    while not result or (step_id not in in_flight):
      step_id, result = self._processed_queue.get().result()
    if isinstance(result, Exception):
      raise result
    in_flight.pop(step_id).success(result)

  def close(self):
    """Cleanup thread pool."""
    for f in self._pending:
      f.cancel()
    self._pool.shutdown()  # Wait for pool to cleanup before we cleanup storage.
    super(ThreadHybridEngine, self).close()


def _process_initializer(node_builder, storage):
  """Another pickle-able top-level function that provides multi-processes' initial states.

  States are returned as a tuple. States are `Closable` so they can be cleaned up once
  processes are done.
  """
  return node_builder, Storage.clone(storage)


def _execute_step(cache_save, debug, process_state, step):
  """A picklable top-level function to help support local multiprocessing uses.
  Executes the Step for the given node builder and storage, and returns a tuple of step id and
  result or exception. Since step execution is only on cache misses, this also saves result
  to the cache.
  """
  node_builder, storage = process_state
  step_id = step.step_id

  def execute():
    resolved_request = storage.resolve_request(step)
    result = resolved_request(node_builder)
    if debug:
      _try_pickle(result)
    cache_save(step, result)
    return storage.key_for_result(result)

  try:
    return step_id, execute()
  except Exception as e:
    # Trap any exception raised by the execution node that bubbles up, and
    # pass this back to our main thread for handling.
    logger.warn(traceback.format_exc())
    return step_id, e


class LocalMultiprocessEngine(ConcurrentEngine):
  """An engine that runs tasks locally and in parallel when possible using a process pool."""

  def __init__(self, scheduler, storage, cache=None, pool_size=None, debug=True):
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

    execute_step = functools.partial(_execute_step, self._maybe_cache_put, debug)

    self._processed_queue = Queue()
    self.node_builder = scheduler.node_builder()
    process_initializer = functools.partial(self._initializer, self.node_builder, self._storage)
    self._pool = StatefulPool(self._pool_size, process_initializer, execute_step)
    self._debug = debug

  @property
  def _initializer(self):
    return _process_initializer

  def _submit(self, step):
    _try_pickle(step)
    self._pool.submit(step)

  def start(self):
    self._pool.start()

  def close(self):
    self._pool.close()

  def _is_async_node(self, node):
    return True

  def _submit_until(self, pending_submission, in_flight, n):
    """Submit pending while there's capacity, and more than `n` items pending_submission."""
    to_submit = min(len(pending_submission) - n, self._pool_size - len(in_flight))
    submitted = 0
    for _ in range(to_submit):
      step, promise = pending_submission.pop(last=False)

      if self._is_async_node(step.node):
        if step.step_id in in_flight:
          raise InFlightException('{} is already in_flight!'.format(step))

        step = self._storage.key_for_request(step)
        result = self._maybe_cache_get(step)
        if result is not None:
          # Skip in_flight on cache hit.
          promise.success(result)
        else:
          in_flight[step.step_id] = promise
          self._submit(step)
          submitted += 1
      else:
        keyed_request = self._storage.key_for_request(step)
        result = self._maybe_cache_get(keyed_request)
        if result is None:
          result = step(self.node_builder)
          self._maybe_cache_put(keyed_request, result)
        promise.success(result)

    return submitted

  def _await_one(self, in_flight):
    """Await one completed step, and remove it from in_flight."""
    if not in_flight:
      raise InFlightException('Awaited an empty pool!')
    step_id, result = self._pool.await_one_result()
    if isinstance(result, Exception):
      raise result
    result = self._storage.resolve_result(result)
    if step_id not in in_flight:
      raise InFlightException(
        'Received unexpected work from the Executor: {} vs {}'.format(step_id, in_flight.keys()))
    in_flight.pop(step_id).success(result)
