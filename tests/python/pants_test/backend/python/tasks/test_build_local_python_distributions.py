# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re
from builtins import next, str
from textwrap import dedent

from pants.backend.native.register import rules as native_backend_rules
from pants.backend.python.register import rules as python_backend_rules
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.tasks.build_local_python_distributions import \
  BuildLocalPythonDistributions
from pants.util.collections import assert_single_element
from pants_test.backend.python.tasks.python_task_test_base import (PythonTaskTestBase,
                                                                   check_wheel_platform_matches_host,
                                                                   name_and_platform)
from pants_test.engine.scheduler_test_base import SchedulerTestBase


class TestBuildLocalPythonDistributions(PythonTaskTestBase, SchedulerTestBase):
  @classmethod
  def task_type(cls):
    return BuildLocalPythonDistributions

  _dist_specs = {
    'src/python/dist:universal_dist': {
      'key': 'universal',
      'sources': ['foo.py', 'bar.py', '__init__.py', 'setup.py'],
      'filemap': {
        'src/python/dist/__init__.py': '',
        'src/python/dist/foo.py': 'print("foo")',
        'src/python/dist/bar.py': 'print("bar")',
        'src/python/dist/setup.py': dedent("""
        from setuptools import setup, find_packages
        setup(
          name='universal_dist',
          version='0.0.0',
          packages=find_packages()
        )
      """)
      }
    },
    'src/python/plat_specific_dist:plat_specific_dist': {
      'key': 'platform_specific',
      'sources': ['__init__.py', 'setup.py', 'native_source.c'],
      'filemap': {
        'src/python/plat_specific_dist/__init__.py': '',
        'src/python/plat_specific_dist/setup.py': dedent("""
        from distutils.core import Extension
        from setuptools import setup, find_packages
        setup(
          name='platform_specific_dist',
          version='0.0.0',
          packages=find_packages(),
          extensions=[Extension('native_source', sources=['native_source.c'])]
        )
      """),
        'src/python/plat_specific_dist/native_source.c': dedent("""
        #include <Python.h>

        static PyObject * native_source(PyObject *self, PyObject *args) {
          return Py_BuildValue("s", "Hello from C!");
        }

        static PyMethodDef Methods[] = {
          {"native_source", native_source, METH_VARARGS, ""},
          {NULL, NULL, 0, NULL}
        };

        PyMODINIT_FUNC initnative_source(void) {
          (void) Py_InitModule("native_source", Methods);
        }
      """),
      }
    },
  }

  def setUp(self):
    super(TestBuildLocalPythonDistributions, self).setUp()

    self.target_dict = {}

    # Create a python_dist() target from each specification and insert it into `self.target_dict`.
    for target_spec, file_spec in self._dist_specs.items():
      filemap = file_spec['filemap']
      for rel_path, content in filemap.items():
        self.create_file(rel_path, content)

      sources = file_spec['sources']
      python_dist_tgt = self.make_target(spec=target_spec,
                                         target_type=PythonDistribution,
                                         sources=sources)
      key = file_spec['key']
      self.target_dict[key] = python_dist_tgt

  def _all_dist_targets(self):
    return list(self.target_dict.values())

  def _scheduling_context(self, **kwargs):
    rules = (
      native_backend_rules() +
      python_backend_rules()
    )
    scheduler = self.mk_scheduler(rules=rules)
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

  def _create_distribution_synthetic_target(self, python_dist_target):
    context = self._scheduling_context(
      target_roots=[python_dist_target],
      for_task_types=[BuildLocalPythonDistributions])
    self.assertEquals(set(self._all_dist_targets()), set(context.build_graph.targets()))
    python_create_distributions_task = self.create_task(context)
    python_create_distributions_task.execute()
    synthetic_tgts = set(context.build_graph.targets()) - set(self._all_dist_targets())
    self.assertEquals(1, len(synthetic_tgts))
    synthetic_target = next(iter(synthetic_tgts))

    snapshot_version = self._get_dist_snapshot_version(
      python_create_distributions_task, python_dist_target)

    return context, synthetic_target, snapshot_version

  def test_python_create_universal_distribution(self):
    universal_dist = self.target_dict['universal']
    context, synthetic_target, snapshot_version = self._create_distribution_synthetic_target(
      universal_dist)
    self.assertEquals(['universal_dist==0.0.0+{}'.format(snapshot_version)],
                      [str(x.requirement) for x in synthetic_target.requirements.value])

    local_wheel_products = context.products.get('local_wheels')
    local_wheel = self._retrieve_single_product_at_target_base(local_wheel_products, universal_dist)
    _, _, wheel_platform = name_and_platform(local_wheel)
    self.assertEqual('any', wheel_platform)

  def test_python_create_platform_specific_distribution(self):
    platform_specific_dist = self.target_dict['platform_specific']
    context, synthetic_target, snapshot_version = self._create_distribution_synthetic_target(
      platform_specific_dist)
    self.assertEquals(['platform_specific_dist==0.0.0+{}'.format(snapshot_version)],
                      [str(x.requirement) for x in synthetic_target.requirements.value])

    local_wheel_products = context.products.get('local_wheels')
    local_wheel = self._retrieve_single_product_at_target_base(
      local_wheel_products, platform_specific_dist)
    self.assertTrue(check_wheel_platform_matches_host(local_wheel))
