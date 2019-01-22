# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str
from textwrap import dedent

from twitter.common.collections import OrderedDict

from pants.backend.python.targets.python_distribution import PythonDistribution
from pants_test.backend.python.tasks.python_task_test_base import name_and_platform
from pants_test.backend.python.tasks.util.build_local_dists_test_base import \
  BuildLocalPythonDistributionsTestBase


class TestBuildLocalDistsNativeSources(BuildLocalPythonDistributionsTestBase):

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

  ])

  def test_python_create_universal_distribution(self):
    universal_dist = self.target_dict['universal']
    context, synthetic_target, snapshot_version = self._create_distribution_synthetic_target(
      universal_dist)
    self.assertEqual(['universal_dist==0.0.0+{}'.format(snapshot_version)],
                      [str(x.requirement) for x in synthetic_target.requirements.value])

    local_wheel_products = context.products.get('local_wheels')
    local_wheel = self._retrieve_single_product_at_target_base(local_wheel_products, universal_dist)
    _, _, wheel_platform = name_and_platform(local_wheel)
    self.assertEqual('any', wheel_platform)
