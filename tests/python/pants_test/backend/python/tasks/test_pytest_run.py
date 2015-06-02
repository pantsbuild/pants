# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os
import xml.dom.minidom as DOM
from textwrap import dedent

import coverage

from pants.backend.python.tasks.pytest_run import PytestRun
from pants.base.exceptions import TestFailedTaskError
from pants.util.contextutil import environment_as, pushd
from pants_test.backend.python.tasks.python_task_test import PythonTaskTest


class PythonTestBuilderTestBase(PythonTaskTest):
  @classmethod
  def task_type(cls):
    return PytestRun

  def run_tests(self, targets, **options):
    test_options = {
      'colors': False,
      'level': 'info'  # When debugging a test failure it may be helpful to set this to 'debug'.
    }
    test_options.update(options)
    self.set_options(**test_options)
    context = self.context(target_roots=targets)
    pytest_run_task = self.create_task(context)
    with pushd(self.build_root):
      pytest_run_task.execute()

  def run_failing_tests(self, targets, failed_targets, **options):
    with self.assertRaises(TestFailedTaskError) as cm:
      self.run_tests(targets=targets, **options)
    self.assertEqual(set(failed_targets), set(cm.exception.failed_targets))


class PythonTestBuilderTestEmpty(PythonTestBuilderTestBase):
  def test_empty(self):
    self.run_tests(targets=[])


class PythonTestBuilderTest(PythonTestBuilderTestBase):
  def setUp(self):
    super(PythonTestBuilderTest, self).setUp()
    self.create_file(
        'lib/core.py',
        dedent("""
          def one():  # line 1
            return 1  # line 2
                      # line 3
                      # line 4
          def two():  # line 5
            return 2  # line 6
        """).strip())
    self.add_to_build_file(
        'lib',
        dedent("""
          python_library(
            name='core',
            sources=[
              'core.py'
            ]
          )
        """))

    self.create_file(
        'tests/test_core_green.py',
        dedent("""
          import unittest2 as unittest

          import core

          class CoreGreenTest(unittest.TestCase):
            def test_one(self):
              self.assertEqual(1, core.one())
        """))
    self.create_file(
        'tests/test_core_red.py',
        dedent("""
          import core

          def test_two():
            assert 1 == core.two()
        """))
    self.add_to_build_file(
        'tests',
        dedent("""
          python_tests(
            name='green',
            sources=[
              'test_core_green.py'
            ],
            dependencies=[
              'lib:core'
            ],
            coverage=[
              'core'
            ]
          )

          python_tests(
            name='red',
            sources=[
              'test_core_red.py'
            ],
            dependencies=[
              'lib:core'
            ],
            coverage=[
              'core'
            ]
          )

          python_tests(
            name='all',
            sources=[
              'test_core_green.py',
              'test_core_red.py'
            ],
            dependencies=[
              'lib:core'
            ]
          )

          python_tests(
            name='all-with-coverage',
            sources=[
              'test_core_green.py',
              'test_core_red.py'
            ],
            dependencies=[
              'lib:core'
            ],
            coverage=[
              'core'
            ]
          )
        """))
    self.green = self.target('tests:green')

    self.red = self.target('tests:red')
    self.all = self.target('tests:all')
    self.all_with_coverage = self.target('tests:all-with-coverage')

  def test_green(self):
    self.run_tests(targets=[self.green])

  def test_red(self):
    self.run_failing_tests(targets=[self.red], failed_targets=[self.red])

  def test_mixed(self):
    self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red])

  def test_junit_xml(self):
    # We expect xml of the following form:
    # <testsuite errors=[Ne] failures=[Nf] skips=[Ns] tests=[Nt] ...>
    #   <testcase classname="..." name="..." .../>
    #   <testcase classname="..." name="..." ...>
    #     <failure ...>...</failure>
    #   </testcase>
    # </testsuite>

    report_basedir = os.path.join(self.build_root, 'dist', 'junit')
    with environment_as(JUNIT_XML_BASE=report_basedir):
      self.run_failing_tests(targets=[self.red, self.green], failed_targets=[self.red])

      files = glob.glob(os.path.join(report_basedir, '*.xml'))
      self.assertEqual(1, len(files))
      junit_xml = files[0]
      with open(junit_xml) as fp:
        print(fp.read())

      root = DOM.parse(junit_xml).documentElement
      self.assertEqual(2, len(root.childNodes))
      self.assertEqual(2, int(root.getAttribute('tests')))
      self.assertEqual(1, int(root.getAttribute('failures')))
      self.assertEqual(0, int(root.getAttribute('errors')))
      self.assertEqual(0, int(root.getAttribute('skips')))

      children_by_test_name = dict((elem.getAttribute('name'), elem) for elem in root.childNodes)
      self.assertEqual(0, len(children_by_test_name['test_one'].childNodes))
      self.assertEqual(1, len(children_by_test_name['test_two'].childNodes))
      self.assertEqual('failure', children_by_test_name['test_two'].firstChild.nodeName)

  def coverage_data_file(self):
    return os.path.join(self.build_root, '.coverage')

  def load_coverage_data(self, path):
    data_file = self.coverage_data_file()
    self.assertTrue(os.path.isfile(data_file))
    coverage_data = coverage.coverage(data_file=data_file)
    coverage_data.load()
    _, all_statements, not_run_statements, _ = coverage_data.analysis(path)
    return all_statements, not_run_statements

  def test_coverage_simple(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))
    covered_file = os.path.join(self.build_root, 'lib', 'core.py')
    with environment_as(PANTS_PY_COVERAGE='1'):
      self.run_tests(targets=[self.green])
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([6], not_run_statements)

      self.run_failing_tests(targets=[self.red], failed_targets=[self.red])
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([2], not_run_statements)

      self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red])
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([], not_run_statements)

      # The all target has no coverage attribute and the code under test does not follow the
      # auto-discover pattern so we should get no coverage.
      self.run_failing_tests(targets=[self.all], failed_targets=[self.all])
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([1, 2, 5, 6], not_run_statements)

      self.run_failing_tests(targets=[self.all_with_coverage], failed_targets=[self.all_with_coverage])
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([], not_run_statements)

  def test_coverage_modules(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))
    covered_file = os.path.join(self.build_root, 'lib', 'core.py')
    with environment_as(PANTS_PY_COVERAGE='modules:does_not_exist,nor_does_this'):
      # modules: should trump .coverage
      self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red])
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([1, 2, 5, 6], not_run_statements)

    with environment_as(PANTS_PY_COVERAGE='modules:core'):
      self.run_failing_tests(targets=[self.all], failed_targets=[self.all])
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([], not_run_statements)

  def test_coverage_paths(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))
    covered_file = os.path.join(self.build_root, 'lib', 'core.py')
    with environment_as(PANTS_PY_COVERAGE='paths:does_not_exist/,nor_does_this/'):
      # paths: should trump .coverage
      self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red])
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([1, 2, 5, 6], not_run_statements)

    with environment_as(PANTS_PY_COVERAGE='paths:core.py'):
      self.run_failing_tests(targets=[self.all], failed_targets=[self.all])
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([], not_run_statements)

  def test_sharding(self):
    self.run_failing_tests(targets=[self.red, self.green], failed_targets=[self.red], shard='0/2')
    self.run_tests(targets=[self.red, self.green], shard='1/2')

  def test_sharding_single(self):
    self.run_failing_tests(targets=[self.red], failed_targets=[self.red], shard='0/1')

  def test_sharding_invalid_shard_too_small(self):
    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], shard='-1/1')

  def test_sharding_invalid_shard_too_big(self):
    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], shard='1/1')

  def test_sharding_invalid_shard_bad_format(self):
    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], shard='1')

    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], shard='1/2/3')

    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], shard='1/a')
