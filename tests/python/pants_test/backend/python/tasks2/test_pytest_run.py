# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

import coverage

from pants.backend.python.tasks2.gather_sources import GatherSources
from pants.backend.python.tasks2.pytest_prep import PytestPrep
from pants.backend.python.tasks2.pytest_run import PytestResult, PytestRun
from pants.backend.python.tasks2.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks2.select_interpreter import SelectInterpreter
from pants.base.exceptions import ErrorWhileTesting, TaskError
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase
from pants_test.tasks.task_test_base import ensure_cached


class PytestTestBase(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    return PytestRun

  _CONFTEST_CONTENT = '# I am an existing root-level conftest file.'

  def run_tests(self, targets, *passthru_args, **options):
    """Run the tests in the specified targets, with the specified PytestRun task options."""
    context = self._prepare_test_run(targets, *passthru_args, **options)
    self._do_run_tests(context)

  def run_failing_tests(self, targets, failed_targets, *passthru_args, **options):
    context = self._prepare_test_run(targets, *passthru_args, **options)
    with self.assertRaises(ErrorWhileTesting) as cm:
      self._do_run_tests(context)
    self.assertEqual(set(failed_targets), set(cm.exception.failed_targets))

  def try_run_tests(self, targets, *passthru_args, **options):
    try:
      self.run_tests(targets, *passthru_args, **options)
      return []
    except ErrorWhileTesting as e:
      return e.failed_targets

  def _prepare_test_run(self, targets, *passthru_args, **options):
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
    pp_task_type = self.synthesize_task_subtype(PytestPrep, 'pp_scope')
    context = self.context(for_task_types=[si_task_type, rr_task_type, gs_task_type, pp_task_type],
                           target_roots=targets,
                           passthru_args=list(passthru_args))
    si_task_type(context, os.path.join(self.pants_workdir, 'si')).execute()
    rr_task_type(context, os.path.join(self.pants_workdir, 'rr')).execute()
    gs_task_type(context, os.path.join(self.pants_workdir, 'gs')).execute()
    pp_task_type(context, os.path.join(self.pants_workdir, 'pp')).execute()
    return context

  def _do_run_tests(self, context):
    pytest_run_task = self.create_task(context)
    with pushd(self.build_root):
      pytest_run_task.execute()


class PytestTestEmpty(PytestTestBase):
  def test_empty(self):
    self.run_tests(targets=[])


class PytestTestFailedPexRun(PytestTestBase):
  class AlwaysFailingPexRunPytestRun(PytestRun):
    @classmethod
    def set_up(cls):
      junitxml_dir = safe_mkdtemp()
      cls.junitxml_path = os.path.join(junitxml_dir, 'junit.xml')
      cls._get_junit_xml_path = lambda *args, **kwargs: cls.junitxml_path
      return lambda: safe_rmtree(junitxml_dir)

    def _do_run_tests_with_args(self, *args, **kwargs):
      return PytestResult.rc(42)

  @classmethod
  def task_type(cls):
    return cls.AlwaysFailingPexRunPytestRun

  def setUp(self):
    super(PytestTestFailedPexRun, self).setUp()
    self.create_file(
      'tests/test_green.py',
      dedent("""
          import unittest

          class GreenTest(unittest.TestCase):
            def test_green(self):
              self.assertTrue(True)
        """))
    self.add_to_build_file('tests', 'python_tests(sources=["test_green.py"])')
    self.tests = self.target('tests')

    self.addCleanup(self.AlwaysFailingPexRunPytestRun.set_up())

  def do_test_failed_pex_run(self):
    with self.assertRaises(TaskError) as cm:
      self.run_tests(targets=[self.tests])

    # We expect a `TaskError` as opposed to an `ErrorWhileTesting` since execution fails outside
    # the actual test run.
    self.assertEqual(TaskError, type(cm.exception))

  def test_failed_pex_run(self):
    self.do_test_failed_pex_run()

  def test_failed_pex_run_does_not_see_prior_failures(self):
    # Setup a prior failure.
    with open(self.AlwaysFailingPexRunPytestRun.junitxml_path, mode='wb') as fp:
      fp.write(b"""
          <testsuite errors="0" failures="1" name="pytest" skips="0" tests="1" time="0.001">
            <testcase classname="tests.test_green.GreenTest"
                      file=".pants.d/gs/8...6-DefaultFingerprintStrategy_e88d80fa140b/test_green.py"
                      line="4"
                      name="test_green"
                      time="0.0001">
              <failure message="AssertionError: False is not true"/>
            </testcase>
          </testsuite>
          """)

    self.do_test_failed_pex_run()


class PytestTest(PytestTestBase):
  def setUp(self):
    super(PytestTest, self).setUp()

    self.set_options_for_scope('cache.{}'.format(self.options_scope),
                               read_from=None,
                               write_to=None)

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
      'tests/test_core_green2.py',
      dedent("""
          import unittest2 as unittest

          import core

          class CoreGreen2Test(unittest.TestCase):
            def test_one(self):
              self.assertEqual(1, core.one())
        """))
    self.create_file(
      'tests/test_core_green3.py',
      dedent("""
          import unittest2 as unittest

          import core

          class CoreGreen3Test(unittest.TestCase):
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
    self.create_file(
      'tests/conftest.py', self._CONFTEST_CONTENT
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
            name='green2',
            sources=[
              'test_core_green2.py'
            ],
            dependencies=[
              'lib:core'
            ],
            coverage=[
              'core'
            ]
          )

          python_tests(
            name='green3',
            sources=[
              'test_core_green3.py'
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

          python_tests(
            name='green-with-conftest',
            sources=[
              'conftest.py',
              'test_core_green.py',
            ],
            dependencies=[
              'lib:core',
            ]
          )
        """))
    self.green = self.target('tests:green')
    self.green2 = self.target('tests:green2')
    self.green3 = self.target('tests:green3')

    self.red = self.target('tests:red')
    self.red_in_class = self.target('tests:red_in_class')
    self.sleep_no_timeout = self.target('tests:sleep_no_timeout')
    self.sleep_timeout = self.target('tests:sleep_timeout')
    self.error = self.target('tests:error')
    self.failure_outside_function = self.target('tests:failure_outside_function')

    self.all = self.target('tests:all')
    self.all_with_coverage = self.target('tests:all-with-coverage')
    self.green_with_conftest = self.target('tests:green-with-conftest')

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_error(self):
    """Test that a test that errors rather than fails shows up in ErrorWhileTesting."""

    self.run_failing_tests(targets=[self.red, self.green, self.error],
                           failed_targets=[self.red, self.error])

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_error_outside_function(self):
    self.run_failing_tests(targets=[self.red, self.green, self.failure_outside_function],
                           failed_targets=[self.red, self.failure_outside_function])

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_green(self):
    self.run_tests(targets=[self.green])

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_caches_greens_fast(self):
    self.run_tests(targets=[self.green, self.green2, self.green3], fast=True)

  @ensure_cached(PytestRun, expected_num_artifacts=3)
  def test_cache_greens_slow(self):
    self.run_tests(targets=[self.green, self.green2, self.green3], fast=False)

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_out_of_band_deselect_fast_success(self):
    self.run_tests([self.green, self.red], '-kno_tests_should_match_at_all', fast=True)

  # NB: Both red and green are cached. Red because its skipped via deselect and so runs (noops)
  # successfully. This is OK since the -k passthru is part of the task fingerprinting.
  @ensure_cached(PytestRun, expected_num_artifacts=2)
  def test_out_of_band_deselect_no_fast_success(self):
    self.run_tests([self.green, self.red], '-ktest_core_green', fast=False)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_red(self):
    self.run_failing_tests(targets=[self.red], failed_targets=[self.red])

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_fail_fast_skips_second_red_test_with_single_chroot(self):
    self.run_failing_tests(targets=[self.red, self.red_in_class],
                           failed_targets=[self.red],
                           fail_fast=True,
                           fast=False)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_fail_fast_skips_second_red_test_with_isolated_chroot(self):
    self.run_failing_tests(targets=[self.red, self.red_in_class],
                           failed_targets=[self.red_in_class],
                           fail_fast=True,
                           fast=True)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_red_test_in_class(self):
    self.run_failing_tests(targets=[self.red_in_class], failed_targets=[self.red_in_class])

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_mixed(self):
    self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red])

  def assert_test_info(self, junit_xml_dir, *expected):
    test_info = PytestRun.parse_test_info(xml_path=junit_xml_dir, error_handler=self.assertIsNone)
    self.assertEqual({name for (name, _) in expected}, set(test_info.keys()))
    for name, result in expected:
      test_details = test_info[name]
      self.assertEqual(result, test_details['result_code'])
      self.assertGreater(test_details['time'], 0)

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_green_junit_xml_dir(self):
    with temporary_dir() as junit_xml_dir:
      self.run_tests(targets=[self.green], junit_xml_dir=junit_xml_dir)

      self.assert_test_info(junit_xml_dir, ('test_one', 'success'))

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_red_junit_xml_dir(self):
    with temporary_dir() as junit_xml_dir:
      self.run_failing_tests(targets=[self.red, self.green],
                             failed_targets=[self.red],
                             junit_xml_dir=junit_xml_dir,
                             fast=True,
                             fail_fast=False)

      self.assert_test_info(junit_xml_dir, ('test_one', 'success'), ('test_two', 'failure'))

  def coverage_data_file(self):
    return os.path.join(self.build_root, '.coverage')

  def load_coverage_data(self):
    path = os.path.join(self.build_root, 'lib', 'core.py')
    data_file = self.coverage_data_file()
    self.assertTrue(os.path.isfile(data_file))
    coverage_data = coverage.coverage(data_file=data_file)
    coverage_data.load()
    _, all_statements, not_run_statements, _ = coverage_data.analysis(path)
    return all_statements, not_run_statements

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_coverage_auto_option(self):
    simple_coverage_kwargs = {'coverage': 'auto'}

    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    self.run_tests(targets=[self.green], **simple_coverage_kwargs)
    all_statements, not_run_statements = self.load_coverage_data()
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([6], not_run_statements)

    self.run_failing_tests(targets=[self.red], failed_targets=[self.red], **simple_coverage_kwargs)
    all_statements, not_run_statements = self.load_coverage_data()
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([2], not_run_statements)

    self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red],
                           **simple_coverage_kwargs)
    all_statements, not_run_statements = self.load_coverage_data()
    self.assertEqual([1, 2, 5, 6], all_statements)
    # The green target run should be cached and thus not covered in this second run.
    self.assertEqual([2], not_run_statements)

    # The all target has no coverage attribute and the code under test does not follow the
    # auto-discover pattern so we should get no coverage.
    self.run_failing_tests(targets=[self.all], failed_targets=[self.all], **simple_coverage_kwargs)
    all_statements, not_run_statements = self.load_coverage_data()
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([1, 2, 5, 6], not_run_statements)

    self.run_failing_tests(targets=[self.all_with_coverage],
                           failed_targets=[self.all_with_coverage], **simple_coverage_kwargs)
    all_statements, not_run_statements = self.load_coverage_data()
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_coverage_modules_dne_option(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    # Explicit modules should trump .coverage.
    self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red],
                           coverage='does_not_exist,nor_does_this')
    all_statements, not_run_statements = self.load_coverage_data()
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([1, 2, 5, 6], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_coverage_modules_option(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    self.run_failing_tests(targets=[self.all], failed_targets=[self.all], coverage='core')
    all_statements, not_run_statements = self.load_coverage_data()
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_coverage_paths_option(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    self.run_failing_tests(targets=[self.all], failed_targets=[self.all], coverage='lib/')
    all_statements, not_run_statements = self.load_coverage_data()
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_sharding(self):
    shard0_failed_targets = self.try_run_tests(targets=[self.red, self.green], test_shard='0/2')
    shard1_failed_targets = self.try_run_tests(targets=[self.red, self.green], test_shard='1/2')

    # One shard should have no failed targets and the other should have found red failed. We're not
    # sure how pytest will order tests, so measure this in an order-agnostic manner.
    self.assertEqual([self.red], shard0_failed_targets + shard1_failed_targets)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_sharding_single(self):
    self.run_failing_tests(targets=[self.red], failed_targets=[self.red], test_shard='0/1')

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_sharding_invalid_shard_too_small(self):
    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], test_shard='-1/1')

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_sharding_invalid_shard_too_big(self):
    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], test_shard='1/1')

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_sharding_invalid_shard_bad_format(self):
    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], test_shard='1')

    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], test_shard='1/2/3')

    with self.assertRaises(PytestRun.InvalidShardSpecification):
      self.run_tests(targets=[self.green], test_shard='1/a')
