# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import Queue as queue
import traceback
from collections import defaultdict, namedtuple

from pants.base.worker_pool import Work, WorkerPool


class ExecutionWork(
  namedtuple('ExecutionWork', ['fn', 'dependencies', 'on_success', 'on_failure'])):
  def __call__(self, *args, **kwargs):
    self.fn()

  def run_success_callback(self):
    if self.on_success:
      self.on_success()

  def run_failure_callback(self):
    if self.on_failure:
      self.on_failure()


UNSTARTED = 'Unstarted'
SUCCESS = 'Success'
FAILURE = 'Failure'
QUEUED = 'Queued'


class StatusTable(object):
  DONE_STATES = {SUCCESS, FAILURE}

  def __init__(self, keys):
    self._statuses = {key: UNSTARTED for key in keys}

  def mark_as(self, state, key):
    self._statuses[key] = state

  def all_done(self):
    return all(s in self.DONE_STATES for s in self._statuses.values())

  def unfinished_work(self):
    """Returns a dict of name to current status, only including work that's not done"""
    return {key: stat for key, stat in self._statuses.items() if stat not in self.DONE_STATES}

  def get(self, key):
    return self._statuses.get(key)

  def has_failures(self):
    return any(stat == FAILURE for stat in self._statuses.values())

  def all_successful(self, keys):
    return all(stat == SUCCESS for stat in [self._statuses[k] for k in keys])

  def failed_keys(self):
    return [key for key, stat in self._statuses.items() if stat == FAILURE]


class ExecutionGraph(object):
  """A directed acyclic graph of work to execute."""

  class ExecutionFailure(Exception):
    """Raised when work units fail during execution"""

  def __init__(self, parent_work_unit, run_tracker, worker_count, log):
    """

    :param parent_work_unit: The work unit for work scheduled within the graph
    :param run_tracker: The run tracker used by the work pool during execution
    :param worker_count: The number of worker threads
    :param log: logger
    """
    self._log = log
    self._parent_work_unit = parent_work_unit
    self._run_tracker = run_tracker
    self._worker_count = worker_count
    self._dependees = defaultdict(list)
    self._work = {}
    self._work_keys_as_scheduled = []

  def log_dot_graph(self):
    for key in self._work_keys_as_scheduled:
      self._log.debug("{} -> {{\n  {}\n}}".format(key, ',\n  '.join(self._dependees[key])))

  def schedule(self, key, fn, dependency_keys, on_success=None, on_failure=None):
    """Inserts work into the execution graph with its dependencies.

    Assumes dependencies have already been scheduled, and raises an error otherwise."""
    self._work_keys_as_scheduled.append(key)
    self._work[key] = ExecutionWork(fn, dependency_keys, on_success, on_failure)
    for dep_name in dependency_keys:
      if dep_name not in self._work:
        raise Exception("Expected {} not scheduled before dependent {}".format(dep_name, key))
      self._dependees[dep_name].append(key)

  def find_work_without_dependencies(self):
    # Topo sort doesn't mean all no-dependency targets are listed first,
    # so we look for all work without dependencies
    return filter(
      lambda key: len(self._work[key].dependencies) == 0, self._work_keys_as_scheduled)

  def execute(self):
    """Runs scheduled work, ensuring all dependencies for each element are done before execution.

    spawns a work pool of the specified size.
    submits all the work without any dependencies
    when a unit of work finishes,
      if it is successful
        calls success callback
        checks for dependees whose dependencies are all successful, and submits them
      if it fails
        calls failure callback
        marks dependees as failed and queues them directly into the finished work queue
    when all work is either successful or failed,
      cleans up the work pool
    if there's an exception on the main thread,
      calls failure callback for unfinished work
      aborts work pool
      re-raises
    """
    self.log_dot_graph()

    status_table = StatusTable(self._work_keys_as_scheduled)
    finished_queue = queue.Queue()

    work_without_dependencies = self.find_work_without_dependencies()
    if len(work_without_dependencies) == 0:
      raise self.ExecutionFailure("No work without dependencies! There must be a "
                                  "circular dependency")

    def worker(work_key, work):
      try:
        work()
        result = (work_key, True, None)
      except Exception as e:
        result = (work_key, False, e)
      finished_queue.put(result)

    pool = WorkerPool(self._parent_work_unit, self._run_tracker, self._worker_count)

    def submit_work(work_keys):
      for work_key in work_keys:
        status_table.mark_as(QUEUED, work_key)
        pool.submit_async_work(Work(worker, [(work_key, (self._work[work_key]))]))

    try:
      submit_work(work_without_dependencies)

      while not status_table.all_done():
        try:
          finished_key, success, value = finished_queue.get(timeout=10)
        except queue.Empty:
          self._log.debug("Waiting on \n  {}\n".format(
            "\n  ".join(
              "{}: {}".format(key, state) for key, state in status_table.unfinished_work().items()
            )))
          continue

        direct_dependees = self._dependees[finished_key]
        finished_work = self._work[finished_key]
        if success:
          status_table.mark_as(SUCCESS, finished_key)
          finished_work.run_success_callback()

          ready_dependees = [dependee for dependee in direct_dependees
                             if status_table.all_successful(self._work[dependee].dependencies)]

          submit_work(ready_dependees)
        else:
          status_table.mark_as(FAILURE, finished_key)
          finished_work.run_failure_callback()

          # propagate failures downstream
          for dependee in direct_dependees:
            finished_queue.put((dependee, False, None))

        self._log.debug("{} finished with status {}".format(finished_key,
                                                            status_table.get(finished_key)))

      pool.shutdown()
    except Exception as e:
      pool.abort()
      # Call failure callbacks for work that's unfinished.
      for key in status_table.unfinished_work().keys():
        self._work[key].run_failure_callback()
      self._log.debug(traceback.format_exc())
      raise self.ExecutionFailure("Error running work: {}".format(e))

    if status_table.has_failures():
      raise self.ExecutionFailure("Failed tasks: {}".format(', '.join(status_table.failed_keys())))
