# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re
from builtins import next

from pants.backend.native.register import rules as native_backend_rules
from pants.backend.python.tasks.build_local_python_distributions import \
  BuildLocalPythonDistributions
from pants.util.collections import assert_single_element
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase
from pants_test.engine.scheduler_test_base import SchedulerTestBase


class BuildLocalPythonDistributionsTestBase(PythonTaskTestBase, SchedulerTestBase):

  @classmethod
  def task_type(cls):
    return BuildLocalPythonDistributions

  # This is an informally-specified nested dict -- see ../test_ctypes.py for an example. Special
  # keys are 'key' (used to index into `self.target_dict`) and 'filemap' (creates files at the
  # specified relative paths). The rest of the keys are fed into `self.make_target()`. An
  # `OrderedDict` of 2-tuples may be used if targets need to be created in a specific order (e.g. if
  # they have dependencies on each other).
  _dist_specs = None
  # By default, we just use a `BuildLocalPythonDistributions` task. When testing with C/C++ targets,
  # we want to compile and link them as well to get the resulting dist to build, so we add those
  # task types here and execute them beforehand.
  _extra_relevant_task_types = None

  def setUp(self):
    super(BuildLocalPythonDistributionsTestBase, self).setUp()

    self.target_dict = {}

    # Create a python_dist() target from each specification and insert it into `self.target_dict`.
    for target_spec, file_spec in self._dist_specs.items():
      file_spec = file_spec.copy()
      filemap = file_spec.pop('filemap')
      for rel_path, content in filemap.items():
        self.create_file(rel_path, content)

      key = file_spec.pop('key')
      dep_targets = []
      for dep_spec in file_spec.pop('dependencies', []):
        existing_tgt_key = self._dist_specs[dep_spec]['key']
        dep_targets.append(self.target_dict[existing_tgt_key])
      python_dist_tgt = self.make_target(spec=target_spec, dependencies=dep_targets, **file_spec)
      self.target_dict[key] = python_dist_tgt

  def _all_specified_targets(self):
    return list(self.target_dict.values())

  def _scheduling_context(self, **kwargs):
    scheduler = self.mk_scheduler(rules=native_backend_rules())
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

  def _get_dist_snapshot_version(self, task, python_dist_target):
    """Get the target's fingerprint, and guess the resulting version string of the built dist.

    Local python_dist() builds are tagged with the versioned target's fingerprint using the
    --tag-build option in the egg_info command. This fingerprint string is slightly modified by
    distutils to ensure a valid version string, and this method finds what that modified version
    string is so we can verify that the produced local dist is being tagged with the correct
    snapshot version.

    The argument we pass to that option begins with a +, which is unchanged. See
    https://www.python.org/dev/peps/pep-0440/ for further information.
    """
    with task.invalidated([python_dist_target], invalidate_dependents=True) as invalidation_check:
      versioned_dist_target = assert_single_element(invalidation_check.all_vts)

    versioned_target_fingerprint = versioned_dist_target.cache_key.hash

    # This performs the normalization that distutils performs to the version string passed to the
    # --tag-build option.
    return re.sub(r'[^a-zA-Z0-9]', '.', versioned_target_fingerprint.lower())

  def _create_task(self, task_type, context):
    return task_type(context, self.test_workdir)

  def _create_distribution_synthetic_target(self, python_dist_target, extra_targets=[]):
    context = self._scheduling_context(
      target_roots=([python_dist_target] + extra_targets),
      for_task_types=([self.task_type()] + self._extra_relevant_task_types))
    self.assertEquals(set(self._all_specified_targets()), set(context.build_graph.targets()))

    python_create_distributions_task = self.create_task(context)
    extra_tasks = [
      self._create_task(task_type, context)
      for task_type in self._extra_relevant_task_types
    ]
    for tsk in extra_tasks:
      tsk.execute()

    python_create_distributions_task.execute()

    synthetic_tgts = set(context.build_graph.targets()) - set(self._all_specified_targets())
    self.assertEquals(1, len(synthetic_tgts))
    synthetic_target = next(iter(synthetic_tgts))

    snapshot_version = self._get_dist_snapshot_version(
      python_create_distributions_task, python_dist_target)

    return context, synthetic_target, snapshot_version
