# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import sys
from contextlib import contextmanager

from twitter.common.collections import maybe_list

from pants.base.workunit import WorkUnit
from pants.build_graph.target import Target
from pants.goal.context import Context
from pants_test.option.util.fakes import create_options


class TestContext(Context):
  """A Context to use during unittesting.

  :API: public

  Stubs out various dependencies that we don't want to introduce in unit tests.

  TODO: Instead of extending the runtime Context class, create a Context interface and have
  TestContext and a runtime Context implementation extend that. This will also allow us to
  isolate the parts of the interface that a Task is allowed to use vs. the parts that the
  task-running machinery is allowed to use.
  """
  class DummyWorkUnit(object):
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

  class DummyRunTracker(object):
    """A runtracker stand-in that does no actual tracking."""
    class DummyArtifactCacheStats(object):
      def add_hits(self, cache_name, targets): pass

      def add_misses(self, cache_name, targets, causes): pass

    artifact_cache_stats = DummyArtifactCacheStats()

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
    return logging.getLogger('test')

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
    return map(f, items)


# TODO: Make Console and Workspace into subsystems, and simplify this signature.
def create_context(options=None, passthru_args=None, target_roots=None, build_graph=None,
                   build_file_parser=None, address_mapper=None,
                   console_outstream=None, workspace=None):
  """Creates a ``Context`` with no options or targets by default.

  :API: public

  :param options: A map of scope -> (map of key to value).

  Other params are as for ``Context``.
  """
  options = create_options(options or {}, passthru_args=passthru_args)
  run_tracker = TestContext.DummyRunTracker()
  target_roots = maybe_list(target_roots, Target) if target_roots else []
  return TestContext(options=options, run_tracker=run_tracker, target_roots=target_roots,
                     build_graph=build_graph, build_file_parser=build_file_parser,
                     address_mapper=address_mapper, console_outstream=console_outstream,
                     workspace=workspace)
