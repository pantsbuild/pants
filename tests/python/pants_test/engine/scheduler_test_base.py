# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.nodes import Throw
from pants.engine.scheduler import Scheduler
from pants.option.global_options import DEFAULT_EXECUTION_OPTIONS
from pants.util.contextutil import temporary_file_path
from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants_test.engine.util import init_native


class SchedulerTestBase:
  """A mixin for classes (tests, presumably) which need to create temporary schedulers.

  TODO: In the medium term, this should be part of pants_test.test_base.TestBase.
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
                   union_rules=None,
                   project_tree=None,
                   work_dir=None,
                   include_trace_on_error=True):
    """Creates a SchedulerSession for a Scheduler with the given Rules installed."""
    rules = rules or []
    work_dir = work_dir or self._create_work_dir()
    project_tree = project_tree or self.mk_fs_tree(work_dir=work_dir)
    local_store_dir = os.path.realpath(safe_mkdtemp())
    scheduler = Scheduler(self._native,
                          project_tree,
                          local_store_dir,
                          rules,
                          union_rules,
                          DEFAULT_EXECUTION_OPTIONS,
                          include_trace_on_error=include_trace_on_error)
    return scheduler.new_session(zipkin_trace_v2=False)

  def context_with_scheduler(self, scheduler, *args, **kwargs):
    return self.context(*args, scheduler=scheduler, **kwargs)

  def execute(self, scheduler, product, *subjects):
    """Runs an ExecutionRequest for the given product and subjects, and returns the result value."""
    request = scheduler.execution_request([product], subjects)
    return self.execute_literal(scheduler, request)

  def execute_literal(self, scheduler, execution_request):
    returns, throws = scheduler.execute(execution_request)
    if throws:
      with temporary_file_path(cleanup=False, suffix='.dot') as dot_file:
        scheduler.visualize_graph_to_file(dot_file)
        raise ValueError('At least one root failed: {}. Visualized as {}'.format(throws, dot_file))
    return list(state.value for _, state in returns)

  def execute_expecting_one_result(self, scheduler, product, subject):
    request = scheduler.execution_request([product], [subject])
    returns, throws = scheduler.execute(request)

    if throws:
      _, state = throws[0]
      raise state.exc

    self.assertEqual(len(returns), 1)

    _, state = returns[0]
    return state

  def execute_raising_throw(self, scheduler, product, subject):
    resulting_value = self.execute_expecting_one_result(scheduler, product, subject)
    self.assertTrue(type(resulting_value) is Throw)

    raise resulting_value.exc
