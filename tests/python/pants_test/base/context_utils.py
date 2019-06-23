# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import sys
from contextlib import contextmanager

from twitter.common.collections import maybe_list

from pants.base.workunit import WorkUnit
from pants.build_graph.target import Target
from pants.goal.context import Context
from pants.goal.run_tracker import RunTrackerLogger


class TestContext(Context):
  """A Context to use during unittesting.

  :API: public

  Stubs out various dependencies that we don't want to introduce in unit tests.

  TODO: Instead of extending the runtime Context class, create a Context interface and have
  TestContext and a runtime Context implementation extend that. This will also allow us to
  isolate the parts of the interface that a Task is allowed to use vs. the parts that the
  task-running machinery is allowed to use.
  """
  class DummyWorkUnit:
    """A workunit stand-in that sends all output to stderr.

   These outputs are typically only used by subprocesses spawned by code under test, not
   the code under test itself, and would otherwise go into some reporting black hole.  The
   testing framework will only display the stderr output when a test fails.

   Provides no other tracking/labeling/reporting functionality. Does not require "opening"
   or "closing".
   """

    def output(self, name):
      return sys.stderr

    def set_outcome(self, outcome):
      return sys.stderr.write('\nWorkUnit outcome: {}\n'.format(WorkUnit.outcome_string(outcome)))

  class DummyRunTracker:
    """A runtracker stand-in that does no actual tracking."""

    def __init__(self):
      self.logger = RunTrackerLogger(self)

    class DummyArtifactCacheStats:
      def add_hits(self, cache_name, targets): pass

      def add_misses(self, cache_name, targets, causes): pass

    artifact_cache_stats = DummyArtifactCacheStats()

    def report_target_info(self, scope, target, keys, val): pass


  class TestLogger(logging.getLoggerClass()):
    """A logger that converts our structured records into flat ones.

    This is so we can use a regular logger in tests instead of our reporting machinery.
    """

    def makeRecord(self, name, lvl, fn, lno, msg, args, exc_info, *pos_args, **kwargs):
      # Python 2 and Python 3 have different arguments for makeRecord().
      # For cross-compatibility, we are unpacking arguments.
      # See https://stackoverflow.com/questions/44329421/logging-makerecord-takes-8-positional-arguments-but-11-were-given.
      msg = ''.join([msg] + [a[0] if isinstance(a, (list, tuple)) else a for a in args])
      args = []
      return super(TestContext.TestLogger, self).makeRecord(
        name, lvl, fn, lno, msg, args, exc_info, *pos_args, **kwargs)

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    logger_cls = logging.getLoggerClass()
    try:
      logging.setLoggerClass(self.TestLogger)
      self._logger = logging.getLogger('test')
    finally:
      logging.setLoggerClass(logger_cls)

  @contextmanager
  def new_workunit(self, name, labels=None, cmd='', log_config=None):
    """
    :API: public
    """
    sys.stderr.write('\nStarting workunit {}\n'.format(name))
    yield TestContext.DummyWorkUnit()

  @property
  def log(self):
    """
    :API: public
    """
    return self._logger

  def submit_background_work_chain(self, work_chain, parent_workunit_name=None):
    """
    :API: public
    """
    # Just do the work synchronously, so we don't need a run tracker, background workers and so on.
    for work in work_chain:
      for args_tuple in work.args_tuples:
        work.func(*args_tuple)

  def subproc_map(self, f, items):
    """
    :API: public
    """
    # Just execute in-process.
    return list(map(f, items))


def create_context_from_options(options, target_roots=None, build_graph=None,
                                build_configuration=None, address_mapper=None,
                                console_outstream=None, workspace=None, scheduler=None):
  """Creates a ``Context`` with the given options and no targets by default.

  :param options: An :class:`pants.option.options.Option`-alike object that supports read methods.

  Other params are as for ``Context``.
  """
  run_tracker = TestContext.DummyRunTracker()
  target_roots = maybe_list(target_roots, Target) if target_roots else []
  return TestContext(options=options, run_tracker=run_tracker, target_roots=target_roots,
                     build_graph=build_graph, build_configuration=build_configuration,
                     address_mapper=address_mapper, console_outstream=console_outstream,
                     workspace=workspace, scheduler=scheduler)
