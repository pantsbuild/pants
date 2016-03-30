# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.exp.engine import LocalSerialEngine
from pants.engine.exp.fs import create_fs_tasks
from pants.engine.exp.nodes import Return
from pants.engine.exp.parser import SymbolTable
from pants.engine.exp.scheduler import LocalScheduler
from pants.engine.exp.storage import Storage
from pants.util.dirutil import safe_mkdtemp, safe_rmtree


class EmptyTable(SymbolTable):
  @classmethod
  def table(cls):
    return {}


class SchedulerTestBase(object):
  """A mixin for classes (tests, presumably) which need to create temporary schedulers.

  TODO: In the medium term, this should be part of pants_test.base_test.BaseTest.
  """

  def mk_scheduler(self,
                   tasks=None,
                   goals=None,
                   storage=None,
                   build_root_src=None,
                   symbol_table_cls=EmptyTable):
    """Creates a Scheduler with "native" tasks already included, and the given additional tasks."""
    goals = goals or dict()
    tasks = tasks or []
    storage = storage or Storage.create(in_memory=True)

    work_dir = safe_mkdtemp()
    self.addCleanup(safe_rmtree, work_dir)
    build_root = os.path.join(work_dir, 'build_root')
    if build_root_src is not None:
      shutil.copytree(build_root_src, build_root)
    else:
      os.mkdir(build_root)

    tasks = list(tasks) + create_fs_tasks()
    project_tree = FileSystemProjectTree(build_root)
    scheduler = LocalScheduler(goals, tasks, storage, project_tree)
    return scheduler, storage, build_root

  def execute_request(self, scheduler, storage, product, *subjects):
    """Creates, runs, and returns an ExecutionRequest for the given product and subjects."""
    request = scheduler.execution_request([product], subjects)
    res = LocalSerialEngine(scheduler, storage).execute(request)
    if res.error:
      raise res.error
    return request

  def execute(self, scheduler, storage, product, *subjects):
    """Runs an ExecutionRequest for the given product and subjects, and returns the result value."""
    request = self.execute_request(scheduler, storage, product, *subjects)
    states = scheduler.root_entries(request).values()
    if any(type(state) is not Return for state in states):
      raise ValueError('At least one request failed: {}'.format(states))
    return list(state.value for state in states)
