# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil
from builtins import object

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.build_graph.address import Address
from pants.engine.nodes import Throw
from pants.engine.scheduler import Scheduler
from pants.option.global_options import DEFAULT_EXECUTION_OPTIONS
from pants.util.contextutil import temporary_file_path
from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants.util.memo import memoized_method
from pants.util.meta import classproperty
from pants_test.engine.util import init_native


class SchedulerTestBase(object):
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
                          work_dir,
                          local_store_dir,
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


class DeclarativeTaskTestBase(SchedulerTestBase):
  """???/experimental blah, makes things declarative, whatever"""

  @classproperty
  def dist_specs(cls):
    """
    This is an informally-specified nested dict -- see ../test_ctypes.py for an example. Special
    keys are 'key' (used to index into `self.target_dict`) and 'filemap' (creates files at the
    specified relative paths). The rest of the keys are fed into `self.make_target()`. An
    `OrderedDict` of 2-tuples may be used if targets need to be created in a specific order (e.g. if
    they have dependencies on each other).
    """
    raise NotImplementedError('dist_specs must be implemented!')

  @classproperty
  def run_before_task_types(cls):
    """
    By default, we just use a `BuildLocalPythonDistributions` task. When testing with C/C++ targets,
    we want to compile and link them as well to get the resulting dist to build, so we add those
    task types here and execute them beforehand.
    """
    return []

  @classproperty
  def run_after_task_types(cls):
    """Tasks to run after local dists are built, similar to `run_before_task_types`."""
    return []

  def populate_target_dict(self):
    self.target_dict = {}

    # Create a target from each specification and insert it into `self.target_dict`.
    for target_spec, target_kwargs in self.dist_specs.items():
      unprocessed_kwargs = target_kwargs.copy()

      target_base = Address.parse(target_spec).spec_path

      # Populate the target's owned files from the specification.
      filemap = unprocessed_kwargs.pop('filemap', {})
      for rel_path, content in filemap.items():
        buildroot_path = os.path.join(target_base, rel_path)
        self.create_file(buildroot_path, content)

      # Ensure any dependencies exist in the target dict (`dist_specs` must then be an
      # OrderedDict).
      # The 'key' is used to access the target in `self.target_dict`.
      key = unprocessed_kwargs.pop('key')
      dep_targets = []
      for dep_spec in unprocessed_kwargs.pop('dependencies', []):
        existing_tgt_key = self.dist_specs[dep_spec]['key']
        dep_targets.append(self.target_dict[existing_tgt_key])

      # Register the generated target.
      generated_target = self.make_target(
        spec=target_spec, dependencies=dep_targets, **unprocessed_kwargs)
      self.target_dict[key] = generated_target

  @memoized_method
  def _synthesize_task_types(self, task_types=()):
    return [
      self.synthesize_task_subtype(tsk, '__tmp_{}'.format(tsk.__name__))
      # TODO: make @memoized_method convert lists to tuples for hashing!
      for tsk in task_types
    ]

  def _all_specified_targets(self):
    return list(self.target_dict.values())

  def _scheduling_context(self, **kwargs):
    scheduler = self.mk_scheduler(rules=self.rules())
    return self.context(scheduler=scheduler, **kwargs)

  def _retrieve_single_product_at_target_base(self, product_mapping, target):
    product = product_mapping.get(target)
    base_dirs = list(product.keys())
    self.assertEqual(1, len(base_dirs))
    single_base_dir = base_dirs[0]
    all_products = product[single_base_dir]
    self.assertEqual(1, len(all_products))
    single_product = all_products[0]
    return single_product

  def _create_task(self, task_type, context):
    return task_type(context, self.test_workdir)

  def invoke_tasks(self, **context_kwargs):
    run_before_synthesized_task_types = self._synthesize_task_types(tuple(self.run_before_task_types))
    run_after_synthesized_task_types = self._synthesize_task_types(tuple(self.run_after_task_types))
    all_synthesized_task_types = run_before_synthesized_task_types + [
      self._testing_task_type,
    ] + run_after_synthesized_task_types

    context = self._scheduling_context(
      for_task_types=all_synthesized_task_types,
      **context_kwargs)
    self.assertEqual(set(self._all_specified_targets()), set(context.build_graph.targets()))

    run_before_task_instances = [
      self._create_task(task_type, context)
      for task_type in run_before_synthesized_task_types
    ]
    current_task_instance = self._create_task(
      self._testing_task_type, context)
    run_after_task_instances = [
      self._create_task(task_type, context)
      for task_type in run_after_synthesized_task_types
    ]
    all_task_instances = run_before_task_instances + [
      current_task_instance
    ] + run_after_task_instances

    for tsk in all_task_instances:
      tsk.execute()

    return (context, run_before_task_instances, current_task_instance, run_after_task_instances)
