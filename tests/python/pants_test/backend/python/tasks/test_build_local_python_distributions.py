# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.python.register import rules as python_backend_rules
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.tasks.build_local_python_distributions import \
  BuildLocalPythonDistributions
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase
from pants_test.engine.scheduler_test_base import SchedulerTestBase


class TestBuildLocalPythonDistributions(PythonTaskTestBase, SchedulerTestBase):
  @classmethod
  def task_type(cls):
    return BuildLocalPythonDistributions

  def setUp(self):
    super(TestBuildLocalPythonDistributions, self).setUp()

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

  def _scheduling_context(self, **kwargs):
    rules = (
      python_backend_rules()
    )
    scheduler = self.mk_scheduler(rules=rules)
    return self.context(scheduler=scheduler, **kwargs)

  def test_python_create_distributions(self):
    context = self._scheduling_context(
      target_roots=[self.python_dist_tgt],
      for_task_types=[BuildLocalPythonDistributions])
    self.assertEquals([self.python_dist_tgt], context.build_graph.targets())
    python_create_distributions_task = self.create_task(context)
    python_create_distributions_task.execute()
    synthetic_tgts = set(context.build_graph.targets()) - {self.python_dist_tgt}
    self.assertEquals(1, len(synthetic_tgts))
    synthetic_target = next(iter(synthetic_tgts))
    self.assertEquals(['my_dist==0.0.0'],
                      [str(x.requirement) for x in synthetic_target.requirements.value])
