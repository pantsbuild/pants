# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import logging
import multiprocessing
import traceback
from abc import abstractmethod, abstractproperty

from concurrent.futures import ThreadPoolExecutor, as_completed
from twitter.common.collections.orderedset import OrderedSet

from pants.base.exceptions import TaskError
from pants.engine.nodes import FilesystemNode
from pants.engine.objects import SerializationError
from pants.engine.processing import StatefulProcessPoolBase, StatefulThreadPoolBase
from pants.engine.storage import Cache, Storage
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


try:
  import cPickle as pickle
except ImportError:
  import pickle


logger = logging.getLogger(__name__)


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

  def _should_cache(self, step_request):
    return step_request.node.is_cacheable

  def _maybe_cache_get(self, step_request):
    return self._cache.get(step_request) if self._should_cache(step_request) else None

  def _maybe_cache_put(self, step_request, step_result):
    if self._should_cache(step_request):
      self._cache.put(step_request, step_result)

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
        # The sole purpose of a keyed request is to get a stable cache key,
        # so we can sort keyed_request.dependencies by keys as opposed to requiring
        # dep nodes to support compare.
        keyed_request = self._storage.key_for_request(step)
        result = self._maybe_cache_get(keyed_request)
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


class ConcurrentEngine(Engine):
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
    super(ConcurrentEngine, self).__init__(scheduler, storage, cache)
    self._pool_size = pool_size if pool_size and pool_size > 0 else 2 * multiprocessing.cpu_count()

    execute_step = functools.partial(_execute_step, self._maybe_cache_put, debug)
    self.node_builder = scheduler.node_builder()
    process_initializer = functools.partial(self._initializer, self.node_builder, self._storage)
    self._pool = self._pool_factory(self._pool_size, process_initializer, execute_step)
    self._debug = debug

  @abstractproperty
  def _pool_factory(self):
    return NotImplemented

  @abstractproperty
  def _initializer(self):
    return NotImplemented

  def _submit(self, step):
    _try_pickle(step)
    self._pool.submit(step)

  def start(self):
    self._pool.start()

  def close(self):
    super(ConcurrentEngine, self).close()
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
          raise Exception('{} is already in_flight!'.format(step))

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
      raise Exception('Awaited an empty pool!')
    step_id, result = self._pool.await_one_result()
    if isinstance(result, Exception):
      raise result
    result = self._storage.resolve_result(result)
    if step_id not in in_flight:
      raise Exception(
        'Received unexpected work from the Executor: {} vs {}'.format(step_id, in_flight.keys()))
    in_flight.pop(step_id).success(result)

  @abstractmethod
  def reduce(self, execution_request):
    """Reduce the given execution graph returning its root products.

    :param execution_request: The description of the goals to achieve.
    :type execution_request: :class:`ExecutionRequest`
    :returns: The root products promised by the execution graph.
    :rtype: dict of (:class:`Promise`, product)
    """


def _thread_initializer(node_builder, storage):
  """Another pickle-able top-level function that provides multi-processes' initial states.

  States are returned as a tuple. States are `Closable` so they can be cleaned up once
  processes are done.
  """
  return node_builder, storage


class LocalMultithreadingEngine(ConcurrentEngine):
  """An engine that runs tasks locally and in parallel when possible using a thread pool."""

  @property
  def _pool_factory(self):
    return StatefulThreadPoolBase

  @property
  def _initializer(self):
    return _thread_initializer

  def reduce(self, execution_request):
    # The main reduction loop:
    # 1. Whenever we don't have enough work to saturate the pool, request more.
    # 2. Whenever the pool is not saturated, submit currently pending work.

    # Step instances which have not been submitted yet.
    # TODO: Scheduler now only sends work once, so a deque should be fine here.
    pending_submission = OrderedSet()
    # Dict from step id to a Promise for Steps that have been submitted.
    in_flight = dict()
    submit_until = functools.partial(self._submit_until, pending_submission, in_flight)
    await_one = functools.partial(self._await_one, in_flight)

    for step_batch in self._scheduler.schedule(execution_request):
      if not step_batch:
        # A batch should only be empty if all dependency work is currently blocked/running.
        if not in_flight and not pending_submission:
          raise Exception('Scheduler provided an empty batch while no work is in progress!')
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


class ThreadHybridEngine(LocalMultithreadingEngine):
  """An engine that runs locally but allows nodes to be optionally run concurrently.

  The decision to run concurrently or in serial is determined by _is_async_node.
  For IO bound nodes we will run concurrently using threads.
  """

  @property
  def _pool_factory(self):
    return StatefulThreadPoolBase

  @property
  def _initializer(self):
    return _thread_initializer

  def _is_async_node(self, node):
    """Override default behavior and handle specific nodes asynchronously."""
    return isinstance(node, (FilesystemNode,))


  def _maybe_cache_get(self, step_request):
    return self._cache.get(step_request) if self._should_cache(step_request) else None

  def _submit_maybe_cache(self, step):
    self._pool.submit(functools.partial(self._maybe_cache_get, step))

  def _submit_until(self, pending_submission, in_flight, n):
    """Submit pending while there's capacity, and more than `n` items pending_submission."""
    to_submit = min(len(pending_submission) - n, self._pool_size - len(in_flight))
    submitted = 0
    for _ in range(to_submit):
      step, promise = pending_submission.pop(last=False)
      if self._is_async_node(step.node):
        if step.step_id in in_flight:
          raise Exception('{} is already in_flight!'.format(step))

        step = self._storage.key_for_request(step)
        result = self._maybe_cache_get(step)
        if result is not None:
          # Skip in_flight on cache hit.
          promise.success(result)
        else:
          in_flight[step.step_id] = promise
          self._submit(step)
          submitted += 1

      # if self._is_async_node(step.node):
      #   import pdb; pdb.set_trace()
      #   if step.step_id in in_flight:
      #     raise Exception('{} is already in_flight!'.format(step))
      #
      #   step = self._storage.key_for_request(step)
      #   in_flight[step.step_id] = promise
      #   self._submit_maybe_cache(step)             # <--- this is our problem child.
      #   self._submit(step)
      #   submitted += 1

      else:
        keyed_request = self._storage.key_for_request(step)
        # We always use a thread pool for cache race.
        with ThreadPoolExecutor(max_workers=self._pool_size) as executor:
          _futures = [
            executor.submit(self._maybe_cache_get, keyed_request),
            executor.submit(step, self.node_builder)
          ]

          for f in as_completed(_futures):
            if f.result() is not None:
              break
          promise.success(f.result())

    return submitted

  def _await_one(self, in_flight):
    """Await one completed step, and remove it from in_flight."""
    if not in_flight:
      raise Exception('Awaited an empty pool!')

    # Drop silently None results (these are cache misses)
    result = None
    while not result:
      step_id, result = self._pool.await_one_result()
      print(step_id, result)
    if isinstance(result, Exception):
      raise result
    result = self._storage.resolve_result(result)
    if step_id not in in_flight:
      raise Exception(
        'Received unexpected work from the Executor: {} vs {}'.format(step_id, in_flight.keys()))
    in_flight.pop(step_id).success(result)


def _process_initializer(node_builder, storage):
  """Another pickle-able top-level function that provides multi-processes' initial states.

  States are returned as a tuple. States are `Closable` so they can be cleaned up once
  processes are done.
  """
  return node_builder, Storage.clone(storage)


class LocalMultiprocessEngine(ConcurrentEngine):
  """An engine that runs tasks locally and in parallel when possible using a process pool."""

  @property
  def _pool_factory(self):
    return StatefulProcessPoolBase

  @property
  def _initializer(self):
    return _process_initializer

  def reduce(self, execution_request):
    # The main reduction loop:
    # 1. Whenever we don't have enough work to saturate the pool, request more.
    # 2. Whenever the pool is not saturated, submit currently pending work.

    # Step instances which have not been submitted yet.
    # TODO: Scheduler now only sends work once, so a deque should be fine here.
    pending_submission = OrderedSet()
    # Dict from step id to a Promise for Steps that have been submitted.
    in_flight = dict()
    submit_until = functools.partial(self._submit_until, pending_submission, in_flight)
    await_one = functools.partial(self._await_one, in_flight)

    for step_batch in self._scheduler.schedule(execution_request):
      if not step_batch:
        # A batch should only be empty if all dependency work is currently blocked/running.
        if not in_flight and not pending_submission:
          raise Exception('Scheduler provided an empty batch while no work is in progress!')
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
