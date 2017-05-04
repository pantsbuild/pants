# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from abc import abstractmethod

from twitter.common.collections import maybe_list

from pants.base.exceptions import TaskError
from pants.engine.nodes import Return, State, Throw
from pants.engine.storage import Cache, Storage
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class ExecutionError(Exception):
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

  def __init__(self, scheduler, storage=None, cache=None, use_cache=True, include_trace_on_error=True):
    """
    :param scheduler: The local scheduler for creating execution graphs.
    :type scheduler: :class:`pants.engine.scheduler.LocalScheduler`
    :param storage: The storage instance for serializables keyed by their hashes.
    :type storage: :class:`pants.engine.storage.Storage`
    :param cache: The cache instance for storing execution results, by default it uses the same
      Storage instance if not specified.
    :type cache: :class:`pants.engine.storage.Cache`
    :param use_cache: True to enable usage of the cache. The cache incurs a large amount of
      overhead for small tasks, and needs TODO: further improvement.
    :type use_cache: bool
    :param include_trace_on_error: Include the trace through the graph upon encountering errors.
    :type include_trace_on_error: bool
    """
    self._include_trace_on_error = include_trace_on_error
    self._scheduler = scheduler
    self._storage = storage or Storage.create()
    self._cache = cache or Cache.create(storage)
    self._use_cache = use_cache

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

  def product_request(self, product, subjects):
    """Executes a request for a singular product type from the scheduler for one or more subjects
    and yields the products.

    :param class product: A product type for the request.
    :param list subjects: A list of subjects for the request.
    :yields: The requested products.
    """
    request = self._scheduler.execution_request([product], subjects)
    result = self.execute(request)
    if result.error:
      raise result.error
    result_items = result.root_products.items()

    # State validation.
    unknown_state_types = tuple(
      type(state) for _, state in result_items if type(state) not in (Throw, Return)
    )
    if unknown_state_types:
      State.raise_unrecognized(unknown_state_types)

    # Throw handling.
    # TODO: See https://github.com/pantsbuild/pants/issues/3912
    throw_root_states = tuple(state for root, state in result_items if type(state) is Throw)
    if throw_root_states:
      if self._include_trace_on_error:
        cumulative_trace = '\n'.join(self._scheduler.trace())
        raise ExecutionError('Received unexpected Throw state(s):\n{}'.format(cumulative_trace))

      if len(throw_root_states) == 1:
        raise throw_root_states[0].exc
      else:
        raise ExecutionError('Multiple exceptions encountered:\n  {}'
                             .format('\n  '.join('{}: {}'.format(type(t.exc).__name__, str(t.exc))
                                                 for t in throw_root_states)))

    # Return handling.
    returns = tuple(state.value for _, state in result_items if type(state) is Return)
    for return_value in returns:
      for computed_product in maybe_list(return_value, expected_type=product):
        yield computed_product

  def cache_stats(self):
    """Returns cache stats for the engine."""
    return self._cache.get_stats()

  def _maybe_cache_get(self, node_entry, runnable):
    """If caching is enabled for the given Entry, create a key and perform a lookup.

    The sole purpose of a keyed request is to get a stable cache key, so we can sort
    keyed_request.dependencies by keys as opposed to requiring dep nodes to support compare.

    :returns: A tuple of a key and result, either of which may be None.
    """
    if not self._use_cache or not runnable.cacheable:
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
    self._scheduler.schedule(execution_request)
