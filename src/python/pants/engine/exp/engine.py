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

from twitter.common.collections.orderedset import OrderedSet

from pants.base.exceptions import TaskError
from pants.engine.exp.objects import Closable, SerializationError
from pants.engine.exp.processing import StatefulPool
from pants.engine.exp.scheduler import StepRequest, StepResult
from pants.engine.exp.storage import Cache, Key, Storage
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
    :type scheduler: :class:`pants.engine.exp.scheduler.LocalScheduler`
    :param storage: The storage instance for serializables keyed by their hashes.
    :type storage: :class:`pants.engine.exp.storage.Storage`
    :param cache: The cache instance for storing execution results, by default it uses the same
      Storage instance if not specified.
    :type cache: :class:`pants.engine.exp.storage.Cache`
    """
    self._scheduler = scheduler
    storage = storage or Storage.create()
    self._storage_io = StorageIO(storage)
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
      self._scheduler.validate()
      return self.Result.finished(self._scheduler.root_entries(execution_request))
    except TaskError as e:
      return self.Result.failure(e)

  def start(self):
    """Start up this engine instance, creating any resources it needs."""
    pass

  def close(self):
    """Shutdown this engine instance, releasing resources it was using."""
    self._storage_io.close()
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
        keyed_request = self._storage_io.key_for_request(step)
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

  Executes the Step for the given node builder and storageIo, and returns a tuple of step id and
  result or exception. Since step execution is only on cache misses, this also saves result
  to the cache.
  """
  node_builder, storage_io = process_state

  step_id = step.step_id
  resolved_request = storage_io.resolve_request(step)
  try:
    result = resolved_request(node_builder)
  except Exception as e:
    # Trap any exception raised by the execution node that bubbles up, and
    # pass this back to our main thread for handling.
    logger.warn(traceback.format_exc())
    return (step_id, e)

  if debug:
    try:
      _try_pickle(result)
    except SerializationError as e:
      return (step_id, e)

  # Save result to cache for this step.
  cache_save(step, result)
  return (step_id, storage_io.key_for_result(result))


def _process_initializer(node_builder, storage_io):
  """Another picklable top-level function that provides multi-processes' initial states.

  States are returned as a tuple. States are `Closable` so they can be cleaned up once
  processes are done.
  """
  return (node_builder, StorageIO(Storage.clone(storage_io._storage)))


class LocalMultiprocessEngine(Engine):
  """An engine that runs tasks locally and in parallel when possible using a process pool."""

  def __init__(self, scheduler, storage, cache=None, pool_size=None, debug=True):
    """
    :param scheduler: The local scheduler for creating execution graphs.
    :type scheduler: :class:`pants.engine.exp.scheduler.LocalScheduler`
    :param storage: The storage instance for serializables keyed by their hashes.
    :type storage: :class:`pants.engine.exp.storage.Storage`
    :param cache: The cache instance for storing execution results, by default it uses the same
      Storage instance if not specified.
    :type cache: :class:`pants.engine.exp.storage.Cache`
    :param int pool_size: The number of worker processes to use; by default 2 processes per core will
                          be used.
    :param bool debug: `True` to turn on pickling error debug mode (slower); True by default.
    """
    super(LocalMultiprocessEngine, self).__init__(scheduler, storage, cache)
    self._pool_size = pool_size if pool_size and pool_size > 0 else 2 * multiprocessing.cpu_count()

    execute_step = functools.partial(_execute_step, self._maybe_cache_put, debug)
    node_builder = scheduler.node_builder()
    process_initializer = functools.partial(_process_initializer, node_builder, self._storage_io)
    self._pool = StatefulPool(self._pool_size, process_initializer, execute_step)
    self._debug = debug

  def _submit(self, step):
    _try_pickle(step)
    self._pool.submit(step)

  def start(self):
    self._pool.start()

  def reduce(self, execution_request):
    # Step instances which have not been submitted yet.
    # TODO: Scheduler now only sends work once, so a deque should be fine here.
    pending_submission = OrderedSet()
    # Dict from step id to a Promise for Steps that have been submitted.
    in_flight = dict()

    def submit_until(n):
      """Submit pending while there's capacity, and more than `n` items pending_submission."""
      to_submit = min(len(pending_submission) - n, self._pool_size - len(in_flight))
      submitted = 0
      for _ in range(to_submit):
        step, promise = pending_submission.pop(last=False)

        if step.step_id in in_flight:
          raise Exception('{} is already in_flight!'.format(step))

        step = self._storage_io.key_for_request(step)
        result = self._maybe_cache_get(step)
        if result is not None:
          # Skip in_flight on cache hit.
          promise.success(result)
        else:
          in_flight[step.step_id] = promise
          self._submit(step)
          submitted += 1
      return submitted

    def await_one():
      """Await one completed step, and remove it from in_flight."""
      if not in_flight:
        raise Exception('Awaited an empty pool!')
      step_id, result = self._pool.await_one_result()
      result = self._storage_io.resolve_result(result)
      if isinstance(result, Exception):
        raise result
      if step_id not in in_flight:
        raise Exception('Received unexpected work from the Executor: {} vs {}'.format(step_id, in_flight.keys()))
      in_flight.pop(step_id).success(result)

    # The main reduction loop:
    # 1. Whenever we don't have enough work to saturate the pool, request more.
    # 2. Whenever the pool is not saturated, submit currently pending work.
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

  def close(self):
    super(LocalMultiprocessEngine, self).close()
    self._pool.close()


class StorageIO(Closable):
  """Control what to be content addresed and content address them (in both ways)."""

  def __init__(self, storage):
    self._storage = storage

  def key_for_request(self, step_request):
    """Make keys for the dependency nodes as well as their states.

    step_request.node isn't keyed is only for convenience because it is used
    in a subsequent is_cacheable check.
    """
    dependencies = {}
    for dep, state in step_request.dependencies.items():
      dependencies[self._storage.put(dep)] = self._storage.put(state)
    return StepRequest(step_request.step_id, step_request.node,
                       dependencies, step_request.project_tree)

  def key_for_result(self, step_result):
    """Make key for result state."""
    state_or_key = self._storage.put(step_result.state)
    return StepResult(state_or_key)

  def resolve_request(self, step_request):
    """Optionally resolve keys if they are present int step_request."""
    dependencies = {}
    for dep, state in step_request.dependencies.items():
      if isinstance(dep, Key):
        dep = self._storage.get(dep)
      if isinstance(state, Key):
        state = self._storage.get(state)
      dependencies[dep] =state

    return StepRequest(step_request.step_id, step_request.node,
                       dependencies, step_request.project_tree)

  def resolve_result(self, step_result):
    """Optionally resolve state key if they are present int step_result."""

    # This could be a SerializationError or other error state.
    if not isinstance(step_result, StepResult):
      return step_result

    if isinstance(step_result.state, Key):
      state = self._storage.get(step_result.state)
    else:
      state = step_result.state
    return StepResult(state)

  def close(self):
    self._storage.close()
