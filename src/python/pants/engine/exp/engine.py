# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import multiprocessing
import os
from abc import abstractmethod

from twitter.common.collections.orderedset import OrderedSet

from pants.base.exceptions import TaskError
from pants.engine.exp.processing import StatefulPool
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


try:
  import cPickle as pickle
except ImportError:
  import pickle


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

  def __init__(self, scheduler):
    """
    :param scheduler: The local scheduler for creating execution graphs.
    :type scheduler: :class:`pants.engine.exp.scheduler.LocalScheduler`
    """
    self._scheduler = scheduler

  def execute(self, build_request):
    """Executes the requested build.

    :param build_request: The description of the goals to achieve.
    :type build_request: :class:`BuildRequest`
    :returns: The result of the run.
    :rtype: :class:`Engine.Result`
    """
    try:
      self.reduce(build_request)
      self._scheduler.validate()
      return self.Result.finished(self._scheduler.root_entries(build_request))
    except TaskError as e:
      return self.Result.failure(e)

  def start(self):
    """Start up this engine instance, creating any resources it needs."""
    pass

  def close(self):
    """Shutdown this engine instance, releasing resources it was using."""
    pass

  @abstractmethod
  def reduce(self, build_request):
    """Reduce the given execution graph returning its root products.

    :param build_request: The description of the goals to achieve.
    :type build_request: :class:`BuildRequest`
    :returns: The root products promised by the execution graph.
    :rtype: dict of (:class:`Promise`, product)
    """


class LocalSerialEngine(Engine):
  """An engine that runs tasks locally and serially in-process."""

  def reduce(self, build_request):
    node_builder = self._scheduler.node_builder()
    for step_batch in self._scheduler.schedule(build_request):
      for step, promise in step_batch:
        promise.success(step(node_builder))


class SerializationError(Exception):
  """Indicates an error serializing input or outputs of an execution node.

  The `LocalMultiprocessEngine` uses this exception to communicate incompatible planner code when
  run in debug mode.  Both the plans and the products they produce must be picklable to be executed
  by the multiprocess engine.
  """


def _try_pickle(obj):
  with open(os.devnull, 'w') as devnull:
    try:
      pickle.dump(obj, devnull)
    except Exception as e:
      # Unfortunately, pickle can raise things other than PickleError instances.  For example it
      # will raise ValueError when handed a lambda; so we handle the otherwise overly-broad
      # `Exception` type here.
      raise SerializationError('Failed to pickle {}: {}'.format(obj, e))


def _execute_step(debug, node_builder, step):
  """A picklable top-level function to help support local multiprocessing uses.
  
  Executes the Step for the given NodeBilder, and returns a tuple of step id and
  result or exception.
  """
  step_id = step.step_id
  try:
    result = step(node_builder)
  except Exception as e:
    # Trap any exception raised by the execution node that bubbles up, and
    # pass this back to our main thread for handling.
    return (step_id, e)

  if debug:
    try:
      _try_pickle(result)
    except SerializationError as e:
      return (step_id, e)
  return (step_id, result)


class LocalMultiprocessEngine(Engine):
  """An engine that runs tasks locally and in parallel when possible using a process pool."""

  def __init__(self, scheduler, pool_size=None, debug=True):
    """
    :param scheduler: The local scheduler for creating execution graphs.
    :type scheduler: :class:`pants.engine.exp.scheduler.LocalScheduler`
    :param int pool_size: The number of worker processes to use; by default 2 processes per core will
                          be used.
    :param bool debug: `True` to turn on pickling error debug mode (slower); True by default.
                       TODO: disable by default, and enable in the pantsbuild/pants repo.
    """
    super(LocalMultiprocessEngine, self).__init__(scheduler)
    self._pool_size = pool_size if pool_size and pool_size > 0 else 2 * multiprocessing.cpu_count()

    execute_step = functools.partial(_execute_step, debug)
    node_builder = scheduler.node_builder()
    self._pool = StatefulPool(self._pool_size, execute_step, node_builder)
    self._debug = debug

  def _submit(self, step):
    _try_pickle(step)
    self._pool.submit(step)

  def start(self):
    self._pool.start()

  def reduce(self, build_request):
    # Step instances which have not been submitted yet.
    # TODO: Scheduler now only sends work once, so a deque should be fine here.
    pending_submission = OrderedSet()
    # Dict from step id to a Promise for Steps that have been submitted.
    in_flight = dict()

    def submit_until(n):
      """Submit pending while there's capacity, and more than `n` items pending_submission."""
      to_submit = min(len(pending_submission) - n, self._pool_size - len(in_flight))
      for _ in range(to_submit):
        step, promise = pending_submission.pop(last=False)
        if step.step_id in in_flight:
          raise Exception('{} is already in_flight!'.format(step))
        in_flight[step.step_id] = promise
        self._submit(step)
      return to_submit

    def await_one():
      """Await one completed step, and remove it from in_flight."""
      if not in_flight:
        raise Exception('Awaited an empty pool!')
      step_id, result = self._pool.await_one_result()
      if isinstance(result, Exception):
        raise result
      if step_id not in in_flight:
        raise Exception('Received unexpected work from the Executor: {} vs {}'.format(step, in_flight.keys()))
      in_flight.pop(step.step_id).success(result)

    # The main reduction loop:
    # 1. Whenever we don't have enough work to saturate the pool, request more.
    # 2. Whenever the pool is not saturated, submit currently pending work.
    for step_batch in self._scheduler.schedule(build_request):
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
      submit_to_capacity()
      await_one()

  def close(self):
    self._pool.close()
