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
from pants.build_graph.register import build_file_aliases as register_core
from pants.util.process_handler import subprocess
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class PythonBinaryCreateTest(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    return PythonBinaryCreate

  @property
  def alias_groups(self):
    return super(PythonBinaryCreateTest, self).alias_groups.merge(register_core())

  def _assert_pex(self, binary, expected_output=None):
    # The easiest way to create products required by the PythonBinaryCreate task is to
    # execute the relevant tasks.
    si_task_type = self.synthesize_task_subtype(SelectInterpreter, 'si_scope')
    gs_task_type = self.synthesize_task_subtype(GatherSources, 'gs_scope')

    task_context = self.context(for_task_types=[si_task_type, gs_task_type], target_roots=[binary])
    run_info_dir = os.path.join(self.pants_workdir, self.options_scope, 'test/info')
    task_context.run_tracker.run_info = RunInfo(run_info_dir)

    si_task_type(task_context, os.path.join(self.pants_workdir, 'si')).execute()
    gs_task_type(task_context, os.path.join(self.pants_workdir, 'gs')).execute()

    test_task = self.create_task(task_context)
    test_task.execute()

    self._check_products(task_context, binary, expected_output=expected_output)

  def _check_products(self, context, binary, expected_output=None):
    pex_name = '{}.pex'.format(binary.address.target_name)
    products = context.products.get('deployable_archives')
    self.assertIsNotNone(products)
    product_data = products.get(binary)
    product_basedir = product_data.keys()[0]
    self.assertEquals(product_data[product_basedir], [pex_name])

    # Check pex copy.
    pex_copy = os.path.join(self.build_root, 'dist', pex_name)
    self.assertTrue(os.path.isfile(pex_copy))

    # Check that the pex runs.
    output = subprocess.check_output(pex_copy)
    if expected_output:
      self.assertEqual(expected_output, output)

  def test_deployable_archive_products_simple(self):
    self.create_python_library('src/python/lib', 'lib', {'lib.py': dedent("""
    import os


    def main():
      os.getcwd()
    """)})

    binary = self.create_python_binary('src/python/bin', 'bin', 'lib.lib:main',
                                       dependencies=['src/python/lib'])
    self._assert_pex(binary)

  def test_deployable_archive_products_files_deps(self):
    self.create_library('src/things', 'files', 'things', sources=['loose_file'])
    self.create_file('src/things/loose_file', 'data!')
    self.create_python_library('src/python/lib', 'lib', {'lib.py': dedent("""
    import os
    import sys


    def main():
      here = os.path.dirname(__file__)
      loose_file = os.path.join(here, '../src/things/loose_file')
      with open(os.path.realpath(loose_file)) as fp:
        sys.stdout.write(fp.read())
    """)})

    binary = self.create_python_binary('src/python/bin', 'bin', 'lib.lib:main',
                                       dependencies=['src/python/lib', 'src/things'])
    self._assert_pex(binary, expected_output='data!')
