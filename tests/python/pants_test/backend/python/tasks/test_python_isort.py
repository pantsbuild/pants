# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
from textwrap import dedent

from pants.backend.python.tasks.python_isort import IsortPythonTask
from pants.util.contextutil import temporary_dir
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonIsortIntegrationTest(PantsRunIntegrationTest):
  TEST_DIR = 'testprojects/src/python/isort/python'
  target = '{}:bad-order'.format(TEST_DIR)

  CONFIG = dedent("""
    [settings]
    line_length=100
    known_future_library=future,pies
    known_first_party=twitter,com.twitter
    known_gen=gen
    indent=2
    multi_line_output=0
    default_section=THIRDPARTY
    sections=FUTURE,STDLIB,FIRSTPARTY,THIRDPARTY
  """)

  def test_isort(self):


    # initial test should fail because of style error.
    args = [
      'compile.pythonstyle',
      '--compile-python-eval-skip',
      '--no-pycheck-import-order-skip',
      self.target
    ]

    initial_test = self.run_pants(args)
    self.assert_failure(initial_test)

    # call fmt.isort to format the files.
    with temporary_dir() as dir:
      with open(os.path.join(dir, '.isort.cfg'), 'w') as cfg:
        cfg.write(self.CONFIG)
        cfg.close()

      format_run = self.run_pants(['fmt.isort', '--settings-path={}'.format(cfg.name), self.target])
      self.assert_success(format_run)

    # final test should pass because files have been formatted.
    final_test = self.run_pants(args)
    self.assert_success(final_test)

  def test_isort_check_only(self):
    # initial test should fail because of style error.
    args = [
      'fmt.isort',
      '--check-only',
      self.target
    ]

    pants_run = self.run_pants(args)
    self.assert_failure(pants_run)


  def tearDown(self):
    # tests change code, so they need to be reset.
    subprocess.check_call(['git', 'checkout', '--', self.TEST_DIR])


class AbcTest(PythonTaskTestBase):


  BAD_IMPORT_ORDER = dedent("""
  from __future__ import (with_statement, division, absolute_import, generators, nested_scopes, print_function,
                          unicode_literals)
  import os
  import logging
  import argparse
  import pkg_resources
  import requests
  from urlparse import urljoin
  from twitter.common.contextutil import temporary_file_path

  from twitter.plans.to.acquire.google import reality
  import yaml

  """)

  @classmethod
  def task_type(cls):
    return IsortPythonTask

  def setUp(self):
    super(AbcTest, self).setUp()
    self._create_graph(broken_b_library=True)

  def _create_graph(self, broken_b_library):
    self.reset_build_graph()
    self.a_library = self.create_python_library('src/python/a', 'a', {'a.py': self.BAD_IMPORT_ORDER})

  def _create_task(self, target_roots, options=None):
    if options:
      self.set_options(**options)
    return self.create_task(self.context(target_roots=target_roots))

  def test_compile(self):
    # for source in self.a_library.sources_relative_to_source_root():
    py_file_path = os.path.join(self.build_root, 'src/python/a/a.py')
    self.assertTrue(os.path.exists(py_file_path))
    with open(py_file_path) as f:
      self.assertEqual(self.BAD_IMPORT_ORDER, f.read())
    isort_task = self._create_task(target_roots=[self.a_library])
    isort_task.execute()
    with open(py_file_path) as f:
      self.assertNotEqual(self.BAD_IMPORT_ORDER, f.read())



    # self.assertEqual([self.a_library], compiled)