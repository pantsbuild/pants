# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil
from builtins import object

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.nodes import Return, Throw
from pants.engine.scheduler import Scheduler
from pants.option.global_options import DEFAULT_EXECUTION_OPTIONS
from pants.util.contextutil import temporary_file_path
from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants_test.engine.util import init_native


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
                   rules=None,
                   project_tree=None,
                   work_dir=None,
                   include_trace_on_error=True):
    """Creates a SchedulerSession for a Scheduler with the given Rules installed."""
    rules = rules or []
    work_dir = work_dir or self._create_work_dir()
    project_tree = project_tree or self.mk_fs_tree(work_dir=work_dir)
    scheduler = Scheduler(self._native,
                          project_tree,
                          work_dir,
                          rules,
                          DEFAULT_EXECUTION_OPTIONS,
                          include_trace_on_error=include_trace_on_error)
    return scheduler.new_session()

  def context_with_scheduler(self, scheduler, *args, **kwargs):
    return self.context(*args, scheduler=scheduler, **kwargs)

  def execute(self, scheduler, product, *subjects):
    """Runs an ExecutionRequest for the given product and subjects, and returns the result value."""
    request = scheduler.execution_request([product], subjects)
    return self.execute_literal(scheduler, request)

  def execute_literal(self, scheduler, execution_request):
    result = scheduler.execute(execution_request)
    if result.error:
      raise result.error
    states = [state for _, state in result.root_products]
    if any(type(state) is not Return for state in states):
      with temporary_file_path(cleanup=False, suffix='.dot') as dot_file:
        scheduler.visualize_graph_to_file(dot_file)
        raise ValueError('At least one root failed: {}. Visualized as {}'.format(states, dot_file))
    return list(state.value for state in states)

  def execute_expecting_one_result(self, scheduler, product, subject):
    request = scheduler.execution_request([product], [subject])
    result = scheduler.execute(request)

    if result.error:
      raise result.error

    states = [state for _, state in result.root_products]
    self.assertEqual(len(states), 1)

    state = states[0]
    if isinstance(state, Throw):
      raise state.exc
    return state

  def execute_raising_throw(self, scheduler, product, subject):
    resulting_value = self.execute_expecting_one_result(scheduler, product, subject)
    self.assertTrue(type(resulting_value) is Throw)

    raise resulting_value.exc
