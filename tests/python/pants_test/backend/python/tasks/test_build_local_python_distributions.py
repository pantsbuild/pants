# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re
from builtins import next, str
from textwrap import dedent

from twitter.common.collections import OrderedDict

from pants.backend.native.register import rules as native_backend_rules
from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.backend.native.targets.native_library import CLibrary, CppLibrary
from pants.backend.native.tasks.c_compile import CCompile
from pants.backend.native.tasks.cpp_compile import CppCompile
from pants.backend.native.tasks.link_shared_libraries import LinkSharedLibraries
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

  _dist_specs = None
  _extra_relevant_task_types = None

  def setUp(self):
    super(TestBuildLocalPythonDistributions, self).setUp()

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


class TestBuildLocalDistsNativeSources(TestBuildLocalPythonDistributions):

  _extra_relevant_task_types = []

  _dist_specs = OrderedDict([

    ('src/python/dist:universal_dist', {
      'key': 'universal',
      'target_type': PythonDistribution,
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
    }),

    ('src/python/plat_specific_dist:plat_specific_dist', {
      'key': 'platform_specific',
      'target_type': PythonDistribution,
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
    }),

  ])

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


class TestBuildLocalDistsWithCtypesNativeSources(TestBuildLocalPythonDistributions):

  _extra_relevant_task_types = [CCompile, CppCompile, LinkSharedLibraries]

  _dist_specs = OrderedDict([

    ('src/python/plat_specific_c_dist:ctypes_c_library', {
      'key': 'ctypes_c_library',
      'target_type': CLibrary,
      'ctypes_native_library': NativeArtifact(lib_name='c-math-lib'),
      'sources': ['c_math_lib.c', 'c_math_lib.h'],
      'filemap': {
        'src/python/plat_specific_c_dist/c_math_lib.c': dedent("""
        #include "c_math_lib.h"
        int add_two(int x) { return x + 2; }
"""),
        'src/python/plat_specific_c_dist/c_math_lib.h': dedent("""
        int add_two(int);
"""),
      }
    }),

    ('src/python/plat_specific_c_dist:plat_specific_ctypes_c_dist', {
      'key': 'platform_specific_ctypes_c_dist',
      'target_type': PythonDistribution,
      'sources': ['__init__.py', 'setup.py'],
      'dependencies': ['src/python/plat_specific_c_dist:ctypes_c_library'],
      'filemap': {
        'src/python/plat_specific_c_dist/__init__.py': '',
        'src/python/plat_specific_c_dist/setup.py': dedent("""
        from setuptools import setup, find_packages
        setup(
          name='platform_specific_ctypes_c_dist',
          version='0.0.0',
          packages=find_packages(),
          data_files=[('', ['libc-math-lib.so'])],
        )
      """),
      }
    }),

    ('src/python/plat_specific_cpp_dist:ctypes_cpp_library', {
      'key': 'ctypes_cpp_library',
      'target_type': CppLibrary,
      'ctypes_native_library': NativeArtifact(lib_name='cpp-math-lib'),
      'sources': ['cpp_math_lib.cpp', 'cpp_math_lib.hpp'],
      'filemap': {
        'src/python/plat_specific_cpp_dist/cpp_math_lib.cpp': '',
        'src/python/plat_specific_cpp_dist/cpp_math_lib.hpp': '',
      },
    }),

    ('src/python/plat_specific_cpp_dist:plat_specific_ctypes_cpp_dist', {
      'key': 'platform_specific_ctypes_cpp_dist',
      'target_type': PythonDistribution,
      'sources': ['__init__.py', 'setup.py'],
      'dependencies': ['src/python/plat_specific_cpp_dist:ctypes_cpp_library'],
      'filemap': {
        'src/python/plat_specific_cpp_dist/__init__.py': '',
        'src/python/plat_specific_cpp_dist/setup.py': dedent("""
        from setuptools import setup, find_packages
        setup(
          name='platform_specific_ctypes_cpp_dist',
          version='0.0.0',
          packages=find_packages(),
          data_files=[('', ['libcpp-math-lib.so'])],
        )
      """),
      }
    }),

  ])

  def test_ctypes_c_dist(self):
    platform_specific_dist = self.target_dict['platform_specific_ctypes_c_dist']
    context, synthetic_target, snapshot_version = self._create_distribution_synthetic_target(
      platform_specific_dist, extra_targets=[self.target_dict['ctypes_c_library']])
    self.assertEquals(['platform_specific_ctypes_c_dist==0.0.0+{}'.format(snapshot_version)],
                      [str(x.requirement) for x in synthetic_target.requirements.value])
    local_wheel_products = context.products.get('local_wheels')
    local_wheel = self._retrieve_single_product_at_target_base(
      local_wheel_products, platform_specific_dist)
    self.assertTrue(check_wheel_platform_matches_host(local_wheel))

  def test_ctypes_cpp_dist(self):
    platform_specific_dist = self.target_dict['platform_specific_ctypes_cpp_dist']
    context, synthetic_target, snapshot_version = self._create_distribution_synthetic_target(
      platform_specific_dist, extra_targets=[self.target_dict['ctypes_cpp_library']])
    self.assertEquals(['platform_specific_ctypes_cpp_dist==0.0.0+{}'.format(snapshot_version)],
                      [str(x.requirement) for x in synthetic_target.requirements.value])

    local_wheel_products = context.products.get('local_wheels')
    local_wheel = self._retrieve_single_product_at_target_base(
      local_wheel_products, platform_specific_dist)
    self.assertTrue(check_wheel_platform_matches_host(local_wheel))
