# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.python.tasks2.gather_sources import GatherSources
from pants.backend.python.tasks2.python_binary_create import PythonBinaryCreate
from pants.backend.python.tasks2.select_interpreter import SelectInterpreter
from pants.base.run_info import RunInfo
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class PythonBinaryCreateTest(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    return PythonBinaryCreate

  def setUp(self):
    super(PythonBinaryCreateTest, self).setUp()

    self.library = self.create_python_library('src/python/lib', 'lib', {'lib.py': dedent("""
    import os


    def main():
      os.getcwd()
    """)})

    self.binary = self.create_python_binary('src/python/bin', 'bin', 'lib.lib:main',
                                            dependencies=['//src/python/lib'])

    # The easiest way to create products required by the PythonBinaryCreate task is to
    # execute the relevant tasks.
    si_task_type = self.synthesize_task_subtype(SelectInterpreter, 'si_scope')
    gs_task_type = self.synthesize_task_subtype(GatherSources, 'gs_scope')

    self.task_context = self.context(for_task_types=[si_task_type, gs_task_type],
                                     target_roots=[self.binary])
    self.run_info_dir = os.path.join(self.pants_workdir, self.options_scope, 'test/info')
    self.task_context.run_tracker.run_info = RunInfo(self.run_info_dir)

    si_task_type(self.task_context, os.path.join(self.pants_workdir, 'si')).execute()
    gs_task_type(self.task_context, os.path.join(self.pants_workdir, 'gs')).execute()

    self.test_task = self.create_task(self.task_context)
    self.dist_root = os.path.join(self.build_root, 'dist')

  def _check_products(self, bin_name):
    pex_name = '{}.pex'.format(bin_name)
    products = self.task_context.products.get('deployable_archives')
    self.assertIsNotNone(products)
    product_data = products.get(self.binary)
    product_basedir = product_data.keys()[0]
    self.assertEquals(product_data[product_basedir], [pex_name])

    # Check pex copy.
    pex_copy = os.path.join(self.dist_root, pex_name)
    self.assertTrue(os.path.isfile(pex_copy))

  def test_deployable_archive_products(self):
    self.test_task.execute()
    self._check_products('bin')
