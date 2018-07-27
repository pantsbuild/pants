# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str
from textwrap import dedent

from twitter.common.collections import OrderedDict

from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.backend.native.targets.native_library import CLibrary, CppLibrary
from pants.backend.native.tasks.c_compile import CCompile
from pants.backend.native.tasks.cpp_compile import CppCompile
from pants.backend.native.tasks.link_shared_libraries import LinkSharedLibraries
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants_test.backend.python.tasks.python_task_test_base import check_wheel_platform_matches_host
from pants_test.backend.python.tasks.util.build_local_dists_test_base import \
  BuildLocalPythonDistributionsTestBase


class TestBuildLocalDistsWithCtypesNativeSources(BuildLocalPythonDistributionsTestBase):

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
