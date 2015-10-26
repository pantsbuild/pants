# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import functools
import multiprocessing
import Queue
from abc import abstractmethod
from threading import Thread

from twitter.common.collections.orderedset import OrderedSet

from pants.base.exceptions import TaskError
from pants.engine.exp.scheduler import Promise
from pants.util.meta import AbstractClass


class FailedToProduce(object):
  """A product type to track failure roots when failing slow."""
  # NB: A picklable top-level type to help support local multiprocessing uses.

  def __init__(self, promise, plan, error=None, priors=None):
    self._promise = promise
    self._plan = plan
    self._error = error
    self._priors = priors

  @property
  def promise(self):
    """Return the promise the failed plan was intended to satisfy.

    :rtype: :class:`pants.engine.exp.scheduler.Promise`
    """
    return self._promise

  @property
  def plan(self):
    """Return the plan that failed.

    :rtype: :class:`pants.engine.exp.scheduler.Plan`
    """
    return self._plan

  @property
  def error(self):
    """Return the error the plan raised.

    The error can be `None` if the plan was not executed because one or more of its promised inputs
    was in error.  In that case you can `walk` to explore the failure path that led here.

    :rtype: :class:`pants.base.exceptions.TaskError`
    """
    return self._error

  def walk(self, postorder=True):
    """Walk this failed product and its priors to explore all failure paths leading here.

    :param bool postorder: When `True`, the traversal order is postorder; ie: root causes are
                           visited 1st; otherwise the current `FailedToProduce` is visited first.
    :returns: An iterator over the graph of failed products that make this failure's promise
              unsatisfiable.
    :rtype: :class:`collections.Iterator` of :class:`FailedToProduce`
    """
    visited = set()
    for prior in self._walk(visited=visited, postorder=postorder):
      yield prior

  def _walk(self, visited, postorder=True):
    if self not in visited:
      visited.add(self)
      if not postorder:
        yield self
      if self._priors:
        for prior in self._priors:
          for p in prior._walk(visited, postorder=postorder):
            yield p
      if postorder:
        yield self

  def __repr__(self):
    return ('FailedToProduce(promise={!r}, plan={!r}, error={!r}, priors={!r})'
            .format(self._promise, self._plan, self._error, self._priors))


def maybe_fail_slow(executable, promise, plan, fail_slow=False):
  """Executes executable respecting fail-slow semantics if requested.

    :param executable: The callable to execute.
    :type executable: A no-argument callable.
    :param promise: The promise the executable's product satisfies.
    :type promise: :class:`pants.engine.exp.scheduler.Promise`
    :param plan: The plan the given `executable` executes.
    :type plan: :class:`pants.engine.exp.scheduler.Plan`
    :param bool fail_slow: `True` to fail slow, returning a chain of `FailedToProduce` products
                           along error paths; `False` to let raised `TaskError`s bubble up.
    :returns: The product of executable; ie: it's return value.  If `fail_slow` is in-effect, this
              may be a `FailedToProduce` product that captures the executable's error.
    """
  # NB: A picklable top-level function to help support local multiprocessing uses.
  try:
    return executable()
  except TaskError as error:
    if fail_slow:
      return FailedToProduce(promise, plan, error=error)
    else:
      raise error


class FailSlowHelper(object):
  """A collection of helper methods for dealing with fail-slow mode and `FailedToProduce` products.

  This helper is safe for mixin to any type.
  """

  @staticmethod
  def collect_inputs(products_by_promise, promise, plan):
    """Collects the promised inputs for the given plan or else returns the failure product.

    If all of the plan's promised inputs are available then a mapping from promises to input
    products is returned; otherwise  a `FailedToProduce` product is constructed that records the
    failure paths.

    :param products_by_promise: A mapping of all collected products so far.
    :type products_by_promise: dict of (:class:`pants.engine.exp.scheduler.Promise`, product)
    :param promise: The promise the given plan satisfies.
    :type promise: :class:`pants.engine.exp.scheduler.Promise`
    :param plan: The plan to collect promised inputs for.
    :type plan: :class:`pants.engine.exp.scheduler.Plan`
    :returns: A mapping from the product types promised to the plan to the products that fulfill
              those promises or else a single `FailedToProduce` product describing why this can't
              be done.
    :rtype: either a dict of (:class:`pants.engine.exp.scheduler.Promise`, product) or a
            :class:`FailedToProduce` product encapsulating the failure paths.
    """
    inputs = {}
    failed_to_produce = []
    for pr in plan.promises:
      product = products_by_promise[pr]
      if isinstance(product, FailedToProduce):
        failed_to_produce.append(product)
      else:
        inputs[pr] = product

    if failed_to_produce:
      return FailedToProduce(promise, plan, priors=failed_to_produce)
    else:
      return inputs

  @staticmethod
  def collect_root_outputs(products_by_promise, execution_graph):
    """Collects the promised products that satisfy the original build request.

    If all of the plan's promised inputs are available then a mapping from promises to input
    products is returned; otherwise  a `FailedToProduce` product is constructed that records the
    failure paths.

    :param products_by_promise: A mapping of all collected products so far.
    :type products_by_promise: dict of (:class:`pants.engine.exp.scheduler.Promise`, product)
    :param execution_graph: The execution graph to collect root products for.
    :type execution_graph: :class:`pants.engine.exp.scheduler.ExecutionGraph`
    :returns: A mapping from the root promised product types to the products that fulfill those
              promises.
    :rtype: dict of (:class:`pants.engine.exp.scheduler.Promise`, product)
    """
    return {root_promise: products_by_promise[root_promise]
            for root_promise in execution_graph.root_promises}

  @staticmethod
  def safe_execute(executable, promise, plan, fail_slow=False):
    """Executes executable respecting fail-slow semantics if requested.

    :param executable: The callable to execute.
    :type executable: A no-argument callable.
    :param promise: The promise the executable's product satisfies.
    :type promise: :class:`pants.engine.exp.scheduler.Promise`
    :param plan: The plan the given `executable` executes.
    :type plan: :class:`pants.engine.exp.scheduler.Plan`
    :param bool fail_slow: `True` to fail slow, returning a chain of `FailedToProduce` products
                           along error paths; `False` to let raised `TaskError`s bubble up.
    :returns: The product of executable; ie: it's return value.  If `fail_slow` is in-effect, this
              may be a `FailedToProduce` product that captures the executable's error.
    """
    return maybe_fail_slow(executable, promise, plan, fail_slow=fail_slow)


class Engine(AbstractClass):
  """An engine for running a pants command line."""

  class PartialFailureError(TaskError):
    """Indicates a partial failure to execute a build request when in fail-slow mode.

    A `PartialFailureError` can be present in an `Engine.Result` but will never be raised by the
    engine.  It serves as an aggregate of all failed promise paths and can be used to inspect them.

    The `exit_code` of a PartialFailureError is always `1`.
    """

    def __init__(self, failed_to_produce):
      """
      :param failed_to_produce: A mapping of failed promises to the `FailedToProduce` product
                                representing the failure.
      :type failed_to_produce: dict of (:class:`pants.engine.exp.scheduler.Promise`,
                                        :class:`FailedToProduce`)
      """
      failed_targets = OrderedSet()
      for ftp in failed_to_produce.values():
        for f in ftp.walk():
          if isinstance(f.error, TaskError):
            failed_targets.update(f.error.failed_targets)

      super(Engine.PartialFailureError, self).__init__(exit_code=1,
                                                       failed_targets=list(failed_targets))
      self._failed_to_produce = failed_to_produce

    @property
    def failed_to_produce(self):
      """Return the mapping of failed promises to `FailedToProduce` products.

      :rtype: dict of (:class:`pants.engine.exp.scheduler.Promise`, :class:`FailedToProduce`)
      """
      return self._failed_to_produce

  class Result(collections.namedtuple('Result', ['error', 'root_products'])):
    """Represents the result of a single engine run."""

    @classmethod
    def finished(cls, root_products):
      """Create a success or partial success result from a finished run.

      Runs can either finish with no errors, satisfying all promises, or they can partially finish
      if run in fail-slow mode producing as many products as possible.
      :param root_products: The mapping of promised root products to the actual products.  In
                            fail-slow mode, some of the products may be :class:`FailedToProduce`
                            products in which case these products will be mapped to an
                            :class:`Engine.PartialFailureError` in the result.
      :type root_products: dict of (:class:`pants.engine.exp.scheduler.Promise`, product)
      :rtype: `Engine.Result`
      """
      failed_to_produce = {promise: product for promise, product in root_products.items()
                           if isinstance(product, FailedToProduce)}
      if not failed_to_produce:
        return cls(error=None, root_products=root_products)
      else:
        return cls(error=Engine.PartialFailureError(failed_to_produce),
                   root_products={promise: product for promise, product in root_products.items()
                                  if not isinstance(product, FailedToProduce)})

    @classmethod
    def failure(cls, error):
      """Create a failure result.

      A failure result represent a fail-fast run with an error.  It presents the error but no
      products.

      :param error: The execution error encountered.
      :type error: :class:`pants.base.exceptions.TaskError`
      :rtype: `Engine.Result`
      """
      return cls(error=error, root_products=None)

  def __init__(self, local_scheduler):
    """
    :param local_scheduler: The local scheduler for creating execution graphs.
    :type local_scheduler: :class:`pants.engine.exp.scheduler.LocalScheduler`
    """
    self._local_scheduler = local_scheduler

  def execute(self, build_request, fail_slow=False):
    """Executes the the requested build.

    :param build_request: The description of the goals to achieve.
    :type build_request: :class:`BuildRequest`
    :param bool fail_slow: `True` to run as much of the build request as possible, returning a mix
                           of successfully produced root products and failed products when failures
                           are encountered.
    :returns: The result of the run.
    :rtype: :class:`Engine.Result`
    """
    execution_graph = self._local_scheduler.execution_graph(build_request)
    try:
      root_products = self.reduce(execution_graph, fail_slow)
      return self.Result.finished(root_products)
    except TaskError as e:
      return self.Result.failure(e)

  @abstractmethod
  def reduce(self, execution_graph, fail_slow=False):
    """Reduce the given execution graph returning its root products.

    :param execution_graph: An execution graph of plans to reduce.
    :type execution_graph: :class:`ExecutionGraph`
    :param bool fail_slow: `True` to run as much of the build request as possible, returning a mix
                           of successfully produced root products and failed products when failures
                           are encountered.
    :returns: The root products promised by the execution graph.
    :rtype: dict of (:class:`Promise`, product)
    """


class LocalSerialEngine(FailSlowHelper, Engine):
  """An engine that runs tasks locally and serially in-process."""

  def reduce(self, execution_graph, fail_slow=False):
    products_by_promise = {}
    for promise, plan in execution_graph.walk():
      inputs = self.collect_inputs(products_by_promise, promise, plan)
      if isinstance(inputs, FailedToProduce):
        # Short circuit plan execution since we don't have all the inputs it needs.
        product = inputs
      else:
        binding = plan.bind(inputs)
        product = self.safe_execute(binding.execute, promise, plan, fail_slow=fail_slow)

      # Index the product across all promises we made for it.
      for subject in plan.subjects:
        products_by_promise[promise.rebind(subject)] = product

    return self.collect_root_outputs(products_by_promise, execution_graph)


def _execute_plan(func, promise, subjects, *args, **kwargs):
  # A picklable top-level function to help support local multiprocessing uses.
  product = func(*args, **kwargs)
  return promise, subjects, product


class LocalMultiprocessEngine(Engine):
  """An engine that runs tasks locally and in parallel when possible using a process pool."""

  def __init__(self, local_scheduler, pool_size=0):
    """
    :param local_scheduler: The local scheduler for creating execution graphs.
    :type local_scheduler: :class:`pants.engine.exp.scheduler.LocalScheduler`
    :param pool: A multiprocessing process pool.
    :type pool: :class:`multiprocessing.Pool`
    """
    super(LocalMultiprocessEngine, self).__init__(local_scheduler)
    self._pool_size = pool_size if pool_size > 0 else multiprocessing.cpu_count()
    self._pool = multiprocessing.Pool(self._pool_size)

  class Executor(FailSlowHelper, Thread):
    LAST_PLAN = object()

    def __init__(self, pool, pool_size, fail_slow=False):
      super(LocalMultiprocessEngine.Executor, self).__init__()

      self._pool = pool
      self._pool_size = pool_size
      self._fail_slow = fail_slow

      self._waiting = []
      self._plans = Queue.Queue(self._pool_size)
      self._results = Queue.Queue()
      self._products_by_promise = {}

      self.name = 'LocalMultiprocessEngine.Executor'
      self.daemon = True
      self.start()

    def enqueue(self, promise, plan):
      self._plans.put((promise, plan))

    def finish(self, execution_graph):
      self._plans.put(self.LAST_PLAN)
      self.join()
      return self.collect_root_outputs(self._products_by_promise, execution_graph)

    def run(self):
      while True:
        done = self._fill_waiting()
        while self._waiting:
          self._submit_all_satisfied()
          self._gather_one()
          if not done:
            break
        if done:
          break

    def _fill_waiting(self):
      while len(self._waiting) < self._pool_size:
        plan = self._plans.get()
        if plan is self.LAST_PLAN:
          return True
        else:
          self._waiting.append(plan)

    def _submit_all_satisfied(self):
      for index, (promise, plan) in enumerate(self._waiting):
        if all(pr in self._products_by_promise for pr in plan.promises):
          self._waiting.pop(index)
          inputs = self.collect_inputs(self._products_by_promise, promise, plan)
          if isinstance(inputs, FailedToProduce):
            # Short circuit plan execution since we don't have all the inputs it needs.
            self._results.put((promise, plan.subjects, inputs))
          else:
            func, args, kwargs = plan.bind(inputs)

            # A no-arg callable that, when executed, produces the promised product.
            executable = functools.partial(func, *args, **kwargs)

            # A wrapper of executable that handles failing slow as needed.
            maybe_fail_slow_executor = functools.partial(maybe_fail_slow,
                                                         executable,
                                                         promise,
                                                         plan,
                                                         self._fail_slow)

            # A picklable execution that returns the promise and subjects in addition to the
            # product produced by executable.  We need this triple to feed the consume side of the
            # _results queue.
            execute_plan = functools.partial(_execute_plan,
                                             maybe_fail_slow_executor,
                                             promise,
                                             plan.subjects)

            self._pool.apply_async(execute_plan, callback=self._results.put)

    def _gather_one(self):
      promise, subjects, product = self._results.get()
      for subject in subjects:
        self._products_by_promise[promise.rebind(subject)] = product

  def reduce(self, execution_graph, fail_slow=False):
    executor = self.Executor(self._pool, self._pool_size, fail_slow=fail_slow)
    for promise, plan in execution_graph.walk():
      executor.enqueue(promise, plan)
    return executor.finish(execution_graph)

  def close(self):
    self._pool.close()
    self._pool.join()
