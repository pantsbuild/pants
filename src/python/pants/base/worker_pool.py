# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import multiprocessing
import signal
import sys
import thread
import threading
from multiprocessing.pool import ThreadPool

from pants.reporting.report import Report


class Work(object):
  """Represents multiple concurrent calls to the same callable."""

  def __init__(self, func, args_tuples, workunit_name=None):
    # A callable.
    self.func = func

    # A list of tuples of args. func will be called once per tuple, concurrently.
    # The length of this list is the cardinality of the work.
    self.args_tuples = args_tuples

    # If specified, each invocation will be executed in a workunit of this name.
    self.workunit_name = workunit_name


class WorkerPool(object):
  """A pool of workers.

  Workers are threads, and so are subject to GIL constraints. Submitting CPU-bound work
  may not be effective. Use this class primarily for IO-bound work.
  """

  def __init__(self, parent_workunit, run_tracker, num_workers):
    self._run_tracker = run_tracker
    # All workers accrue work to the same root.
    self._pool = ThreadPool(processes=num_workers,
                            initializer=self._run_tracker.register_thread,
                            initargs=(parent_workunit, ))
    # We mustn't shutdown when there are pending workchains, as they may need to submit work
    # in the future, and the pool doesn't know about this yet.
    self._pending_workchains = 0
    self._pending_workchains_cond = threading.Condition()  # Protects self._pending_workchains.

    self._shutdown_hooks = []

    self.num_workers = num_workers

  def add_shutdown_hook(self, hook):
    self._shutdown_hooks.append(hook)

  def submit_async_work(self, work, workunit_parent=None, on_success=None, on_failure=None):
    """Submit work to be executed in the background.

    - work: The work to execute.
    - workunit_parent: If specified, work is accounted for under this workunit.
    - on_success: If specified, a callable taking a single argument, which will be a list
                  of return values of each invocation, in order. Called only if all work succeeded.
    - on_failure: If specified, a callable taking a single argument, which is an exception
                  thrown in the work.

    Don't do work in on_success: not only will it block the result handling thread, but
    that thread is not a worker and doesn't have a logging context etc. Use it just to
    submit further work to the pool.
    """
    if work is None or len(work.args_tuples) == 0:  # map_async hangs on 0-length iterables.
      if on_success:
        on_success([])
    else:
      def do_work(*args):
        self._do_work(work.func, *args, workunit_name=work.workunit_name,
                      workunit_parent=workunit_parent, on_failure=on_failure)
      self._pool.map_async(do_work, work.args_tuples, chunksize=1, callback=on_success)

  def submit_async_work_chain(self, work_chain, workunit_parent, done_hook=None):
    """Submit work to be executed in the background.

    - work_chain: An iterable of Work instances. Will be invoked serially. Each instance may
                  have a different cardinality. There is no output-input chaining: the argument
                  tuples must already be present in each work instance.  If any work throws an
                  exception no subsequent work in the chain will be attempted.
    - workunit_parent: Work is accounted for under this workunit.
    - done_hook: If not None, invoked with no args after all work is done, or on error.
    """
    def done():
      if done_hook:
        done_hook()
      with self._pending_workchains_cond:
        self._pending_workchains -= 1
        self._pending_workchains_cond.notify()

    def error(e):
      done()
      self._run_tracker.log(Report.ERROR, '{}'.format(e))

    # We filter out Nones defensively. There shouldn't be any, but if a bug causes one,
    # Pants might hang indefinitely without this filtering.
    work_iter = iter(filter(None, work_chain))

    def submit_next():
      try:
        self.submit_async_work(work_iter.next(), workunit_parent=workunit_parent,
                               on_success=lambda x: submit_next(), on_failure=error)
      except StopIteration:
        done()  # The success case.

    with self._pending_workchains_cond:
      self._pending_workchains += 1
    try:
      submit_next()
    except Exception as e:  # Handles errors in the submission code.
      done()
      self._run_tracker.log(Report.ERROR, '{}'.format(e))
      raise

  def submit_work_and_wait(self, work, workunit_parent=None):
    """Submit work to be executed on this pool, but wait for it to complete.

    - work: The work to execute.
    - workunit_parent: If specified, work is accounted for under this workunit.

    Returns a list of return values of each invocation, in order.  Throws if any invocation does.
    """
    if work is None or len(work.args_tuples) == 0:  # map hangs on 0-length iterables.
      return []
    else:
      def do_work(*args):
        return self._do_work(work.func, *args, workunit_name=work.workunit_name,
                             workunit_parent=workunit_parent)
      # We need to specify a timeout explicitly, because otherwise python ignores SIGINT when waiting
      # on a condition variable, so we won't be able to ctrl-c out.
      return self._pool.map_async(do_work, work.args_tuples, chunksize=1).get(timeout=1000000000)

  def _do_work(self, func, args_tuple, workunit_name, workunit_parent, on_failure=None):
    try:
      if workunit_name:
        with self._run_tracker.new_workunit_under_parent(name=workunit_name, parent=workunit_parent):
          return func(*args_tuple)
      else:
        return func(*args_tuple)
    except KeyboardInterrupt:
      # If a worker thread intercepts a KeyboardInterrupt, we want to propagate it to the main
      # thread.
      thread.interrupt_main()
      raise
    except Exception as e:
      if on_failure:
        # Note that here the work's workunit is closed. So, e.g., it's OK to use on_failure()
        # to close an ancestor workunit.
        on_failure(e)
      raise

  def shutdown(self):
    with self._pending_workchains_cond:
      while self._pending_workchains > 0:
        self._pending_workchains_cond.wait()
      self._pool.close()
      self._pool.join()
      for hook in self._shutdown_hooks:
        hook()

  def abort(self):
    self._pool.terminate()


class SubprocPool(object):
  """Singleton for managing multiprocessing.Pool instances

  Subprocesses (including multiprocessing.Pool workers) can inherit locks in poorly written
  libraries (eg zlib) if other threads in the parent process happen to be holding them at the
  moment the worker is fork()'ed. Thus it is important to create any subprocesses BEFORE
  starting any threads, or they may deadlock mysteriously when sent a particular piece of work.

  This is accomplished in pants by these initializing pools early, when creating the RunTracker.

  However, in tests, RunTrackers are created repeatedly, as part of creating Contexts that
  are used briefly and discarded. Creating a new subprocess pool every time is expensive, and will
  lead to os.fork failing once too many processes are spawned.

  To avoid this, the pools themselves are kept in this singleton and new RunTrackers re-use them.
  """
  _pool = None
  _lock = threading.Lock()

  @staticmethod
  def worker_init():
    # Exit quietly on sigint, otherwise we get {num_procs} keyboardinterrupt stacktraces spewn
    signal.signal(signal.SIGINT, lambda *args: sys.exit())

  @classmethod
  def foreground(cls):
    with cls._lock:
      if cls._pool is None:
        cls._pool = multiprocessing.Pool(initializer=SubprocPool.worker_init)
      return cls._pool

  @classmethod
  def shutdown(cls, force):
    with cls._lock:
      old = cls._pool
      cls._pool = None

    if old:
      if force:
        old.terminate()
      else:
        old.close()
      old.join()
