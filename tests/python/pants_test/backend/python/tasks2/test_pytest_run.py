# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

import coverage
from mock import patch

from pants.backend.python.tasks2.gather_sources import GatherSources
from pants.backend.python.tasks2.pytest_run import PytestRun
from pants.backend.python.tasks2.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks2.select_interpreter import SelectInterpreter
from pants.base.exceptions import TestFailedTaskError
from pants.util.contextutil import pushd
from pants.util.timeout import TimeoutReached
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class PythonTestBuilderTestBase(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    return PytestRun

  def run_tests(self, targets, **options):
    """Run the tests in the specified targets, with the specified PytestRun task options.

    Returns the path of the sources pex, so that calling code can map files from the
    source tree to files as pytest saw them.
    """
    context = self._prepare_test_run(targets, **options)
    self._do_run_tests(context)
    return context.products.get_data(GatherSources.PYTHON_SOURCES).path()

  def run_failing_tests(self, targets, failed_targets, **options):
    context = self._prepare_test_run(targets, **options)
    with self.assertRaises(TestFailedTaskError) as cm:
      self._do_run_tests(context)
    self.assertEqual(set(failed_targets), set(cm.exception.failed_targets))
    return context.products.get_data(GatherSources.PYTHON_SOURCES).path()

  def _prepare_test_run(self, targets, **options):
    self.reset_build_graph()
    test_options = {
      'colors': False,
      'level': 'info'  # When debugging a test failure it may be helpful to set this to 'debug'.
    }
    test_options.update(options)
    self.set_options(**test_options)

    # The easiest way to create products required by the PythonTest task is to
    # execute the relevant tasks.
    si_task_type = self.synthesize_task_subtype(SelectInterpreter, 'si_scope')
    rr_task_type = self.synthesize_task_subtype(ResolveRequirements, 'rr_scope')
    gs_task_type = self.synthesize_task_subtype(GatherSources, 'gs_scope')
    context = self.context(for_task_types=[si_task_type, rr_task_type, gs_task_type],
                           target_roots=targets)
    si_task_type(context, os.path.join(self.pants_workdir, 'si')).execute()
    rr_task_type(context, os.path.join(self.pants_workdir, 'rr')).execute()
    gs_task_type(context, os.path.join(self.pants_workdir, 'gs')).execute()
    return context

  def _do_run_tests(self, context):
    pytest_run_task = self.create_task(context)
    with pushd(self.build_root):
      pytest_run_task.execute()


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
    self.create_file(
        'tests/test_core_red_in_class.py',
        dedent("""
          import unittest2 as unittest

          import core

          class CoreRedClassTest(unittest.TestCase):
            def test_one_in_class(self):
              self.assertEqual(1, core.two())
        """))
    self.create_file(
      'tests/test_core_sleep.py',
      dedent("""
          import core

          def test_three():
            assert 1 == core.one()
        """))
    self.create_file(
      'tests/test_error.py',
      dedent("""
        def test_error(bad_fixture):
          pass
      """)
    )
    self.create_file(
      'tests/test_failure_outside_function.py',
      dedent("""
      def null():
        pass

      assert(False)
      """
        )
    )
    self.add_to_build_file(
        'tests',
        dedent("""
          python_tests(
            name='error',
            sources=[
              'test_error.py'
            ],
          )

          python_tests(
            name='failure_outside_function',
            sources=[
              'test_failure_outside_function.py',
            ],
          )

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
              'test_core_red.py',
            ],
            dependencies=[
              'lib:core'
            ],
            coverage=[
              'core'
            ]
          )

          python_tests(
            name='red_in_class',
            sources=[
              'test_core_red_in_class.py',
            ],
            dependencies=[
              'lib:core'
            ],
            coverage=[
              'core'
            ]
          )

          python_tests(
            name='sleep_no_timeout',
            sources=[
              'test_core_sleep.py',
            ],
            timeout = 0,
            dependencies=[
              'lib:core'
            ],
            coverage=[
              'core'
            ]
          )

          python_tests(
            name='sleep_timeout',
            sources=[
              'test_core_sleep.py',
            ],
            timeout = 1,
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
              'test_core_red.py',
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
    self.red_in_class = self.target('tests:red_in_class')
    self.sleep_no_timeout = self.target('tests:sleep_no_timeout')
    self.sleep_timeout = self.target('tests:sleep_timeout')
    self.error = self.target('tests:error')
    self.failure_outside_function = self.target('tests:failure_outside_function')

    self.all = self.target('tests:all')
    self.all_with_coverage = self.target('tests:all-with-coverage')

  def test_error(self):
    """Test that a test that errors rather than fails shows up in TestFailedTaskError."""

    self.run_failing_tests(targets=[self.red, self.green, self.error],
                           failed_targets=[self.red, self.error])

  def test_error_outside_function(self):
    self.run_failing_tests(targets=[self.red, self.green, self.failure_outside_function],
                           failed_targets=[self.red, self.failure_outside_function])

  def test_green(self):
    self.run_tests(targets=[self.green])

  def test_red(self):
    self.run_failing_tests(targets=[self.red], failed_targets=[self.red])

  def test_fail_fast_skips_second_red_test_with_single_chroot(self):
    self.run_failing_tests(targets=[self.red, self.red_in_class], failed_targets=[self.red],
                           fail_fast=True,
                           fast=False)

  def test_fail_fast_skips_second_red_test_with_isolated_chroot(self):
    self.run_failing_tests(targets=[self.red, self.red_in_class], failed_targets=[self.red],
                           fail_fast=True,
                           fast=True)

  def test_red_test_in_class(self):
    # for test in a class, the failure line is in the following format
    # F testprojects/tests/python/pants/constants_only/test_fail.py::TestClassName::test_boom
    self.run_failing_tests(targets=[self.red_in_class], failed_targets=[self.red_in_class])

  def test_mixed(self):
    self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red])

  def test_one_timeout(self):
    # When we have two targets, any of them doesn't have a timeout, and we have no default,
    # then no timeout is set.

    with patch('pants.task.testrunner_task_mixin.Timeout') as mock_timeout:
      self.run_tests(targets=[self.sleep_no_timeout, self.sleep_timeout])

      # Ensures that Timeout is instantiated with no timeout.
      args, kwargs = mock_timeout.call_args
      self.assertEqual(args, (None,))

  def test_timeout(self):
    # Check that a failed timeout returns the right results.

    with patch('pants.task.testrunner_task_mixin.Timeout') as mock_timeout:
      mock_timeout().__exit__.side_effect = TimeoutReached(1)
      self.run_failing_tests(targets=[self.sleep_timeout],
                             failed_targets=[self.sleep_timeout])

      # Ensures that Timeout is instantiated with a 1 second timeout.
      args, kwargs = mock_timeout.call_args
      self.assertEqual(args, (1,))

  def coverage_data_file(self):
    return os.path.join(self.build_root, '.coverage')

  def load_coverage_data(self, path):
    data_file = self.coverage_data_file()
    self.assertTrue(os.path.isfile(data_file))
    coverage_data = coverage.coverage(data_file=data_file)
    coverage_data.load()
    _, all_statements, not_run_statements, _ = coverage_data.analysis(path)
    return all_statements, not_run_statements

  def test_coverage_simple_option(self):
    # TODO(John Sirois): Consider eliminating support for "simple" coverage or at least formalizing
    # the coverage option value that turns this on to "1" or "all" or "simple" = anything formal.
    simple_coverage_kwargs = {'coverage': '1'}

    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    src_root = self.run_tests(targets=[self.green], **simple_coverage_kwargs)
    covered_file = os.path.join(src_root, 'core.py')
    all_statements, not_run_statements = self.load_coverage_data(covered_file)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([6], not_run_statements)

    src_root = self.run_failing_tests(targets=[self.red], failed_targets=[self.red],
                                      **simple_coverage_kwargs)
    covered_file = os.path.join(src_root, 'core.py')
    all_statements, not_run_statements = self.load_coverage_data(covered_file)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([2], not_run_statements)

    src_root = self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red],
                                      **simple_coverage_kwargs)
    covered_file = os.path.join(src_root, 'core.py')
    all_statements, not_run_statements = self.load_coverage_data(covered_file)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([], not_run_statements)

    # The all target has no coverage attribute and the code under test does not follow the
    # auto-discover pattern so we should get no coverage.
    src_root = self.run_failing_tests(targets=[self.all], failed_targets=[self.all],
                                      **simple_coverage_kwargs)
    covered_file = os.path.join(src_root, 'core.py')
    all_statements, not_run_statements = self.load_coverage_data(covered_file)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([1, 2, 5, 6], not_run_statements)

    src_root = self.run_failing_tests(targets=[self.all_with_coverage],
                                      failed_targets=[self.all_with_coverage],
                                      **simple_coverage_kwargs)
    covered_file = os.path.join(src_root, 'core.py')
    all_statements, not_run_statements = self.load_coverage_data(covered_file)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([], not_run_statements)

  def test_coverage_modules_dne_option(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    # modules: should trump .coverage
    src_root = self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red],
                                      coverage='modules:does_not_exist,nor_does_this')
    covered_file = os.path.join(src_root, 'core.py')
    all_statements, not_run_statements = self.load_coverage_data(covered_file)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([1, 2, 5, 6], not_run_statements)

  def test_coverage_modules_option(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    src_root = self.run_failing_tests(targets=[self.all], failed_targets=[self.all],
                                      coverage='modules:core')
    covered_file = os.path.join(src_root, 'core.py')
    all_statements, not_run_statements = self.load_coverage_data(covered_file)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([], not_run_statements)

  def test_coverage_paths_dne_option(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    # paths: should trump .coverage
    src_root = self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red],
                                      coverage='paths:does_not_exist/,nor_does_this/')
    covered_file = os.path.join(src_root, 'core.py')
    all_statements, not_run_statements = self.load_coverage_data(covered_file)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([1, 2, 5, 6], not_run_statements)

  def test_coverage_paths_option(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    src_root = self.run_failing_tests(targets=[self.all], failed_targets=[self.all],
                                      coverage='paths:core.py')
    covered_file = os.path.join(src_root, 'core.py')
    all_statements, not_run_statements = self.load_coverage_data(covered_file)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([], not_run_statements)

  def test_sharding(self):
    self.run_failing_tests(targets=[self.red, self.green], failed_targets=[self.red],
                           test_shard='0/2')
    self.run_tests(targets=[self.red, self.green], test_shard='1/2')

  def test_sharding_single(self):
    self.run_failing_tests(targets=[self.red], failed_targets=[self.red], test_shard='0/1')

  def test_sharding_invalid_shard_too_small(self):
    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], test_shard='-1/1')

  def test_sharding_invalid_shard_too_big(self):
    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], test_shard='1/1')

  def test_sharding_invalid_shard_bad_format(self):
    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], test_shard='1')

    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], test_shard='1/2/3')

    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], test_shard='1/a')
