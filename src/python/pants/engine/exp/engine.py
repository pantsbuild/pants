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

from pants.base.exceptions import TaskError
from pants.engine.exp.scheduler import Promise
from pants.util.meta import AbstractClass


class Engine(AbstractClass):
  """An engine for running a pants command line."""

  class Result(collections.namedtuple('Result', ['exit_code', 'root_products'])):
    """Represents the result of a single engine run."""

    @classmethod
    def success(cls, root_products):
      return cls(exit_code=0, root_products=root_products)

    @classmethod
    def failure(cls, exit_code):
      return cls(exit_code=exit_code, root_products=None)

  def __init__(self, global_scheduler):
    """
    :param global_scheduler: The global scheduler for creating execution graphs.
    :type global_scheduler: :class:`GlobalScheduler`
    """
    self._global_scheduler = global_scheduler

  def execute(self, build_request):
    """Executes the the requested build.

    :param build_request: The description of the goals to achieve.
    :type build_request: :class:`BuildRequest`
    :returns: The result of the run.
    :rtype: :class:`Engine.Result`
    """
    execution_graph = self._global_scheduler.execution_graph(build_request)
    try:
      root_products = self.reduce(execution_graph)
      return self.Result.success(root_products)
    except TaskError as e:
      message = str(e)
      if message:
        print('\nFAILURE: {0}\n'.format(message))
      else:
        print('\nFAILURE\n')
      return self.Result.failure(e.exit_code)

  @abstractmethod
  def reduce(self, execution_graph):
    """Reduce the given execution graph returning its root products.

    :param execution_graph: An execution graph of plans to reduce.
    :type execution_graph: :class:`ExecutionGraph`
    :returns: The root products promised by the execution graph.
    :rtype: dict of (:class:`Promise`, product)
    """


class LocalSerialEngine(Engine):
  """An engine that runs tasks locally and serially in-process."""

  def reduce(self, execution_graph):
    # TODO(John Sirois): Robustify products_by_promise indexed accesses and raise helpful exceptions
    # when there is an unexpected missed promise key.

    products_by_promise = {}
    for product_type, plan in execution_graph.walk():
      binding = plan.bind({promise: products_by_promise[promise] for promise in plan.promises})
      product = binding.execute()
      for subject in plan.subjects:
        products_by_promise[Promise(product_type, subject)] = product

    return {root_promise: products_by_promise[root_promise]
            for root_promise in execution_graph.root_promises}


def _execute_plan(func, product_type, subjects, *args, **kwargs):
  # A picklable top-level function to help support local multiprocessing uses.
  product = func(*args, **kwargs)
  return product_type, subjects, product


class LocalMultiprocessEngine(Engine):
  """An engine that runs tasks locally and in parallel when possible using a process pool."""

  def __init__(self, global_scheduler, pool_size=0):
    """
    :param global_scheduler: The global scheduler for creating execution graphs.
    :type global_scheduler: :class:`GlobalScheduler`
    :param pool: A multiprocessing process pool.
    :type pool: :class:`multiprocessing.Pool`
    """
    super(LocalMultiprocessEngine, self).__init__(global_scheduler)
    self._pool_size = pool_size if pool_size > 0 else multiprocessing.cpu_count()
    self._pool = multiprocessing.Pool(self._pool_size)

  class Executor(Thread):
    LAST_PLAN = object()

    def __init__(self, pool, pool_size):
      super(LocalMultiprocessEngine.Executor, self).__init__()

      self._pool = pool
      self._pool_size = pool_size
      self._waiting = []
      self._plans = Queue.Queue(self._pool_size)
      self._results = Queue.Queue()
      self._products_by_promise = {}

      self.name = 'LocalMultiprocessEngine.Executor'
      self.daemon = True
      self.start()

    def enqueue(self, plan):
      self._plans.put(plan)

    def finish(self, promises):
      self._plans.put(self.LAST_PLAN)
      self.join()
      return {promise: self._products_by_promise[promise] for promise in promises}

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
      for index, (product_type, plan) in enumerate(self._waiting):
        if all(promise in self._products_by_promise for promise in plan.promises):
          self._waiting.pop(index)
          func, args, kwargs = plan.bind({promise: self._products_by_promise[promise]
                                          for promise in plan.promises})
          execute_plan = functools.partial(_execute_plan, func, product_type, plan.subjects)
          self._pool.apply_async(execute_plan, args=args, kwds=kwargs, callback=self._results.put)

    def _gather_one(self):
      product_type, subjects, product = self._results.get()
      for subject in subjects:
        self._products_by_promise[Promise(product_type, subject)] = product

  def reduce(self, execution_graph):
    executor = self.Executor(self._pool, self._pool_size)
    for plan in execution_graph.walk():
      executor.enqueue(plan)
    return executor.finish(execution_graph.root_promises)

  def close(self):
    self._pool.close()
    self._pool.join()
