# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.engine import LocalSerialEngine
from pants.engine.fs import create_fs_rules
from pants.engine.nodes import Return
from pants.engine.parser import SymbolTable
from pants.engine.scheduler import LocalScheduler
from pants.util.contextutil import temporary_file_path
from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants_test.engine.util import init_native


class EmptyTable(SymbolTable):
  @classmethod
  def table(cls):
    return {}


class SchedulerTestBase(object):
  """A mixin for classes (tests, presumably) which need to create temporary schedulers.

  TODO: In the medium term, this should be part of pants_test.base_test.BaseTest.
  """

  _native = init_native()

  def _create_work_dir(self):
    work_dir = safe_mkdtemp()
    self.addCleanup(safe_rmtree, work_dir)
    return work_dir

  def mk_fs_tree(self, build_root_src=None, ignore_patterns=None, work_dir=None):
    """Create a temporary FilesystemProjectTree.

    :param build_root_src: Optional directory to pre-populate from; otherwise, empty.
    :returns: A FilesystemProjectTree.
    """
    work_dir = work_dir or self._create_work_dir()
    build_root = os.path.join(work_dir, 'build_root')
    if build_root_src is not None:
      shutil.copytree(build_root_src, build_root, symlinks=True)
    else:
      os.makedirs(build_root)
    return FileSystemProjectTree(build_root, ignore_patterns=ignore_patterns)

  def mk_scheduler(self,
                   tasks=None,
                   goals=None,
                   project_tree=None,
                   work_dir=None):
    """Creates a Scheduler with "native" tasks already included, and the given additional tasks."""
    goals = goals or dict()
    tasks = tasks or []
    work_dir = work_dir or self._create_work_dir()
    project_tree = project_tree or self.mk_fs_tree(work_dir=work_dir)
    tasks = list(tasks) + create_fs_rules()
    return LocalScheduler(work_dir, goals, tasks, project_tree, self._native)

  def execute_request(self, scheduler, product, *subjects):
    """Creates, runs, and returns an ExecutionRequest for the given product and subjects."""
    request = scheduler.execution_request([product], subjects)
    engine = LocalSerialEngine(scheduler)
    res = engine.execute(request)
    if res.error:
      raise res.error
    return request

  def execute(self, scheduler, product, *subjects):
    """Runs an ExecutionRequest for the given product and subjects, and returns the result value."""
    request = self.execute_request(scheduler, product, *subjects)
    states = scheduler.root_entries(request).values()
    if any(type(state) is not Return for state in states):
      with temporary_file_path(cleanup=False, suffix='.dot') as dot_file:
        scheduler.visualize_graph_to_file(dot_file)
        raise ValueError('At least one request failed: {}. Visualized as {}'.format(states, dot_file))
    return list(state.value for state in states)
