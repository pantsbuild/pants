# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.tasks2.python_create_distributions import PythonCreateDistributions
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class TestPythonCreateDistributions(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    return PythonCreateDistributions

  def setUp(self):
    super(TestPythonCreateDistributions, self).setUp()

    # Setup simple python_dist target
    sources = ['foo.py', 'bar.py', '__init__.py', 'setup.py']
    self.filemap = {
      'src/python/dist/__init__.py': '',
      'src/python/dist/foo.py': 'print("foo")',
      'src/python/dist/bar.py': 'print("bar")',
      'src/python/dist/setup.py': dedent("""
        from setuptools import setup, find_packages
        setup(
          name='my_dist',
          version='0.0.0',
          packages=find_packages()
        )
      """)
    }
    for rel_path, content in self.filemap.items():
      self.create_file(rel_path, content)

    self.python_dist_tgt = self.make_target(spec='src/python/dist:my_dist', 
                                            target_type=PythonDistribution, 
                                            sources=sources)

  def test_python_create_distributions(self):
    context = self.context(target_roots=[self.python_dist_tgt], for_task_types=[PythonCreateDistributions])
    python_create_distributions_task = self.create_task(context,)
    python_create_distributions_task.execute()
    built_dists = context.products.get_data(PythonCreateDistributions.PYTHON_DISTS)
    self.assertGreater(len(built_dists), 0)
    self.assertTrue(any(['my_dist-0.0.0-py2-none-any.whl' in dist for dist in list(built_dists)]))
