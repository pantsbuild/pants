# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import Queue as queue
import threading
import traceback
from collections import defaultdict, deque
from heapq import heappop, heappush

from pants.base.worker_pool import Work


class Job(object):
  """A unit of scheduling for the ExecutionGraph.

  The ExecutionGraph represents a DAG of dependent work. A Job a node in the graph along with the
  keys of its dependent jobs.
  """

  def __init__(self, key, fn, dependencies, size=0, on_success=None, on_failure=None):
    """

    :param key: Key used to reference and look up jobs
    :param fn callable: The work to perform
    :param dependencies: List of keys for dependent jobs
    :param size: Estimated job size used for prioritization
    :param on_success: Zero parameter callback to run if job completes successfully. Run on main
                       thread.
    :param on_failure: Zero parameter callback to run if job completes successfully. Run on main
                       thread."""
    self.key = key
    self.fn = fn
    self.dependencies = dependencies
    self.size = size
    self.on_success = on_success
    self.on_failure = on_failure

  def __call__(self):
    self.fn()

  def run_success_callback(self):
    if self.on_success:
      self.on_success()

  def run_failure_callback(self):
    if self.on_failure:
      self.on_failure()


UNSTARTED = 'Unstarted'
QUEUED = 'Queued'
SUCCESSFUL = 'Successful'
FAILED = 'Failed'
CANCELED = 'Canceled'


class StatusTable(object):
  DONE_STATES = {SUCCESSFUL, FAILED, CANCELED}

  def __init__(self, keys, pending_dependencies_count):
    self._statuses = {key: UNSTARTED for key in keys}
    self._pending_dependencies_count = pending_dependencies_count

  def mark_as(self, state, key):
    self._statuses[key] = state

  def mark_queued(self, key):
    self.mark_as(QUEUED, key)

  def unfinished_items(self):
    """Returns a list of (name, status) tuples, only including entries marked as unfinished."""
    return [(key, stat) for key, stat in self._statuses.items() if stat not in self.DONE_STATES]

  def failed_keys(self):
    return [key for key, stat in self._statuses.items() if stat == FAILED]

  def is_unstarted(self, key):
    return self._statuses.get(key) is UNSTARTED

  def mark_one_successful_dependency(self, key):
    self._pending_dependencies_count[key] -= 1

  def is_ready_to_submit(self, key):
    return self.is_unstarted(key) and self._pending_dependencies_count[key] == 0

  def are_all_done(self):
    return all(s in self.DONE_STATES for s in self._statuses.values())

  def has_failures(self):
    return any(stat is FAILED for stat in self._statuses.values())


class ExecutionFailure(Exception):
  """Raised when work units fail during execution"""

  def __init__(self, message, cause=None):
    if cause:
      message = "{}: {}".format(message, str(cause))
    super(ExecutionFailure, self).__init__(message)
    self.cause = cause


class UnexecutableGraphError(Exception):
  """Base exception class for errors that make an ExecutionGraph not executable"""

  def __init__(self, msg):
    super(UnexecutableGraphError, self).__init__("Unexecutable graph: {}".format(msg))


class NoRootJobError(UnexecutableGraphError):
  def __init__(self):
    super(NoRootJobError, self).__init__(
      "All scheduled jobs have dependencies. There must be a circular dependency.")


class UnknownJobError(UnexecutableGraphError):
  def __init__(self, undefined_dependencies):
    super(UnknownJobError, self).__init__("Undefined dependencies {}"
                                          .format(", ".join(map(repr, undefined_dependencies))))


class JobExistsError(UnexecutableGraphError):
  def __init__(self, key):
    super(JobExistsError, self).__init__("Job already scheduled {!r}"
                                          .format(key))


class ThreadSafeCounter(object):
  def __init__(self):
    self.lock = threading.Lock()
    self._counter = 0

  def get(self):
    with self.lock:
      return self._counter

  def increment(self):
    with self.lock:
      self._counter += 1

  def decrement(self):
    with self.lock:
      self._counter -= 1


class ExecutionGraph(object):
  """A directed acyclic graph of work to execute.

  This is currently only used within jvm compile, but the intent is to unify it with the future
  global execution graph.
  """

  def __init__(self, job_list):
    """

    :param job_list Job: list of Jobs to schedule and run.
    """
    self._dependencies = defaultdict(list)
    self._dependees = defaultdict(list)
    self._jobs = {}
    self._job_keys_as_scheduled = []
    self._job_keys_with_no_dependencies = []

    for job in job_list:
      self._schedule(job)

    unscheduled_dependencies = set(self._dependees.keys()) - set(self._job_keys_as_scheduled)
    if unscheduled_dependencies:
      raise UnknownJobError(unscheduled_dependencies)

    if len(self._job_keys_with_no_dependencies) == 0:
      raise NoRootJobError()

    self._job_priority = self._compute_job_priorities(job_list)

  def format_dependee_graph(self):
    return "\n".join([
      "{} -> {{\n  {}\n}}".format(key, ',\n  '.join(self._dependees[key]))
      for key in self._job_keys_as_scheduled
    ])

  def _schedule(self, job):
    key = job.key
    dependency_keys = job.dependencies
    self._job_keys_as_scheduled.append(key)
    if key in self._jobs:
      raise JobExistsError(key)
    self._jobs[key] = job

    if len(dependency_keys) == 0:
      self._job_keys_with_no_dependencies.append(key)

    self._dependencies[key] = dependency_keys
    for dependency_key in dependency_keys:
      self._dependees[dependency_key].append(key)

  def _compute_job_priorities(self, job_list):
    """Walks the dependency graph breadth-first, starting from the most dependent tasks,
     and computes the job priority as the sum of the jobs sizes along the critical path."""

    job_size = {job.key: job.size for job in job_list}
    job_priority = defaultdict(int)

    bfs_queue = deque()
    for job in job_list:
      if len(self._dependees[job.key]) == 0:
        job_priority[job.key] = job_size[job.key]
        bfs_queue.append(job.key)

    satisfied_dependees_count = defaultdict(int)
    while len(bfs_queue) > 0:
      job_key = bfs_queue.popleft()
      for dependency_key in self._dependencies[job_key]:
        job_priority[dependency_key] = \
          max(job_priority[dependency_key],
              job_size[dependency_key] + job_priority[job_key])
        satisfied_dependees_count[dependency_key] += 1
        if satisfied_dependees_count[dependency_key] == len(self._dependees[dependency_key]):
          bfs_queue.append(dependency_key)

    return job_priority

  def execute(self, pool, log):
    """Runs scheduled work, ensuring all dependencies for each element are done before execution.

    :param pool: A WorkerPool to run jobs on
    :param log: logger for logging debug information and progress

    submits all the work without any dependencies to the worker pool
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
    log.debug(self.format_dependee_graph())

    status_table = StatusTable(self._job_keys_as_scheduled,
                               {key: len(self._jobs[key].dependencies) for key in self._job_keys_as_scheduled})
    finished_queue = queue.Queue()

    heap = []
    jobs_in_flight = ThreadSafeCounter()

    def put_jobs_into_heap(job_keys):
      for job_key in job_keys:
        # minus because jobs with larger priority should go first
        heappush(heap, (-self._job_priority[job_key], job_key))

    def try_to_submit_jobs_from_heap():
      def worker(worker_key, work):
        try:
          work()
          result = (worker_key, SUCCESSFUL, None)
        except Exception as e:
          result = (worker_key, FAILED, e)
        finished_queue.put(result)
        jobs_in_flight.decrement()

      while len(heap) > 0 and jobs_in_flight.get() < pool.num_workers:
        priority, job_key = heappop(heap)
        jobs_in_flight.increment()
        status_table.mark_queued(job_key)
        pool.submit_async_work(Work(worker, [(job_key, (self._jobs[job_key]))]))

    def submit_jobs(job_keys):
      put_jobs_into_heap(job_keys)
      try_to_submit_jobs_from_heap()

    try:
      submit_jobs(self._job_keys_with_no_dependencies)

      while not status_table.are_all_done():
        try:
          finished_key, result_status, value = finished_queue.get(timeout=10)
        except queue.Empty:
          log.debug("Waiting on \n  {}\n".format("\n  ".join(
            "{}: {}".format(key, state) for key, state in status_table.unfinished_items())))
          try_to_submit_jobs_from_heap()
          continue

        finished_job = self._jobs[finished_key]
        direct_dependees = self._dependees[finished_key]
        status_table.mark_as(result_status, finished_key)

        # Queue downstream tasks.
        if result_status is SUCCESSFUL:
          try:
            finished_job.run_success_callback()
          except Exception as e:
            log.debug(traceback.format_exc())
            raise ExecutionFailure("Error in on_success for {}".format(finished_key), e)

          ready_dependees = []
          for dependee in direct_dependees:
            status_table.mark_one_successful_dependency(dependee)
            if status_table.is_ready_to_submit(dependee):
              ready_dependees.append(dependee)

          submit_jobs(ready_dependees)
        else:  # Failed or canceled.
          try:
            finished_job.run_failure_callback()
          except Exception as e:
            log.debug(traceback.format_exc())
            raise ExecutionFailure("Error in on_failure for {}".format(finished_key), e)

          # Propagate failures downstream.
          for dependee in direct_dependees:
            if status_table.is_unstarted(dependee):
              status_table.mark_queued(dependee)
              finished_queue.put((dependee, CANCELED, None))

        # Log success or failure for this job.
        if result_status is FAILED:
          log.error("{} failed: {}".format(finished_key, value))
        else:
          log.debug("{} finished with status {}".format(finished_key, result_status))
    except ExecutionFailure:
      raise
    except Exception as e:
      # Call failure callbacks for jobs that are unfinished.
      for key, state in status_table.unfinished_items():
        self._jobs[key].run_failure_callback()
      log.debug(traceback.format_exc())
      raise ExecutionFailure("Error running job", e)

    if status_table.has_failures():
      raise ExecutionFailure("Failed jobs: {}".format(', '.join(status_table.failed_keys())))
