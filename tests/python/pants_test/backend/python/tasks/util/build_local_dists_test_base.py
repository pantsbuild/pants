# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
from builtins import next, str

from pants.backend.native.register import rules as native_backend_rules
from pants.backend.native.subsystems.libc_dev import LibcDev
from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.tasks.build_local_python_distributions import \
  BuildLocalPythonDistributions
from pants.backend.python.tasks.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks.select_interpreter import SelectInterpreter
from pants.build_graph.address import Address
from pants.util.collections import assert_single_element
from pants.util.memo import memoized_method
from pants.util.meta import classproperty
from pants_test.backend.python.tasks.python_task_test_base import (PythonTaskTestBase,
                                                                   name_and_platform)
from pants_test.engine.scheduler_test_base import SchedulerTestBase


class BuildLocalPythonDistributionsTestBase(PythonTaskTestBase, SchedulerTestBase):

  @classmethod
  def task_type(cls):
    return BuildLocalPythonDistributions

  @classproperty
  def _dist_specs(cls):
    """
    This is an informally-specified nested dict -- see ../test_ctypes.py for an example. Special
    keys are 'key' (used to index into `self.target_dict`) and 'filemap' (creates files at the
    specified relative paths). The rest of the keys are fed into `self.make_target()`. An
    `OrderedDict` of 2-tuples may be used if targets need to be created in a specific order (e.g. if
    they have dependencies on each other).
    """
    raise NotImplementedError('_dist_specs must be implemented!')

  @classproperty
  def _run_before_task_types(cls):
    """
    By default, we just use a `BuildLocalPythonDistributions` task. When testing with C/C++ targets,
    we want to compile and link them as well to get the resulting dist to build, so we add those
    task types here and execute them beforehand.
    """
    return [SelectInterpreter]

  @classproperty
  def _run_after_task_types(cls):
    """Tasks to run after local dists are built, similar to `_run_before_task_types`."""
    return [ResolveRequirements]

  @memoized_method
  def _synthesize_task_types(self, task_types=()):
    return [
      self.synthesize_task_subtype(tsk, '__tmp_{}'.format(tsk.__name__))
      # TODO: make @memoized_method convert lists to tuples for hashing!
      for tsk in task_types
    ]

  def setUp(self):
    super(BuildLocalPythonDistributionsTestBase, self).setUp()

    self.target_dict = {}

    # Create a target from each specification and insert it into `self.target_dict`.
    for target_spec, target_kwargs in self._dist_specs.items():
      unprocessed_kwargs = target_kwargs.copy()

      target_base = Address.parse(target_spec).spec_path

      # Populate the target's owned files from the specification.
      filemap = unprocessed_kwargs.pop('filemap', {})
      for rel_path, content in filemap.items():
        buildroot_path = os.path.join(target_base, rel_path)
        self.create_file(buildroot_path, content)

      # Ensure any dependencies exist in the target dict (`_dist_specs` must then be an
      # OrderedDict).
      # The 'key' is used to access the target in `self.target_dict`.
      key = unprocessed_kwargs.pop('key')
      dep_targets = []
      for dep_spec in unprocessed_kwargs.pop('dependencies', []):
        existing_tgt_key = self._dist_specs[dep_spec]['key']
        dep_targets.append(self.target_dict[existing_tgt_key])

      # Register the generated target.
      generated_target = self.make_target(
        spec=target_spec, dependencies=dep_targets, **unprocessed_kwargs)
      self.target_dict[key] = generated_target

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
    run_before_synthesized_task_types = self._synthesize_task_types(tuple(self._run_before_task_types))
    python_create_distributions_task_type = self._testing_task_type
    run_after_synthesized_task_types = self._synthesize_task_types(tuple(self._run_after_task_types))
    all_synthesized_task_types = run_before_synthesized_task_types + [
      python_create_distributions_task_type,
    ] + run_after_synthesized_task_types

    context = self._scheduling_context(
      target_roots=([python_dist_target] + extra_targets),
      for_task_types=all_synthesized_task_types,
      for_subsystems=[PythonRepos, LibcDev],
      # TODO(#6848): we should be testing all of these with both of our toolchains.
      options={
        'native-build-settings': {
          'toolchain_variant': 'llvm',
        },
      })
    self.assertEqual(set(self._all_specified_targets()), set(context.build_graph.targets()))

    run_before_task_instances = [
      self._create_task(task_type, context)
      for task_type in run_before_synthesized_task_types
    ]
    python_create_distributions_task_instance = self._create_task(
      python_create_distributions_task_type, context)
    run_after_task_instances = [
      self._create_task(task_type, context)
      for task_type in run_after_synthesized_task_types
    ]
    all_task_instances = run_before_task_instances + [
      python_create_distributions_task_instance
    ] + run_after_task_instances

    for tsk in all_task_instances:
      tsk.execute()

    synthetic_tgts = set(context.build_graph.targets()) - set(self._all_specified_targets())
    self.assertEqual(1, len(synthetic_tgts))
    synthetic_target = next(iter(synthetic_tgts))

    snapshot_version = self._get_dist_snapshot_version(
      python_create_distributions_task_instance, python_dist_target)

    return context, synthetic_target, snapshot_version

  def _assert_dist_and_wheel_identity(self, expected_name, expected_version, expected_platform,
                                      dist_target, **kwargs):
    context, synthetic_target, fingerprint_suffix = self._create_distribution_synthetic_target(
      dist_target, **kwargs)
    resulting_dist_req = assert_single_element(synthetic_target.requirements.value)
    expected_snapshot_version = '{}+{}'.format(expected_version, fingerprint_suffix)
    self.assertEquals(
      '{}=={}'.format(expected_name, expected_snapshot_version),
      str(resulting_dist_req.requirement))

    local_wheel_products = context.products.get('local_wheels')
    local_wheel = self._retrieve_single_product_at_target_base(local_wheel_products, dist_target)
    dist, version, platform = name_and_platform(local_wheel)
    self.assertEquals(dist, expected_name)
    self.assertEquals(version, expected_snapshot_version)
    self.assertEquals(platform, expected_platform)
