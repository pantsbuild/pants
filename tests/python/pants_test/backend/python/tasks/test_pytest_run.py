# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import os
from contextlib import contextmanager
from textwrap import dedent

import coverage
from six.moves import configparser

from pants.backend.python.tasks.gather_sources import GatherSources
from pants.backend.python.tasks.pytest_prep import PytestPrep
from pants.backend.python.tasks.pytest_run import PytestResult, PytestRun
from pants.backend.python.tasks.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks.select_interpreter import SelectInterpreter
from pants.base.exceptions import ErrorWhileTesting, TaskError
from pants.build_graph.target import Target
from pants.source.source_root import SourceRootConfig
from pants.util.contextutil import pushd, temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase
from pants_test.subsystem.subsystem_util import init_subsystem
from pants_test.task_test_base import ensure_cached


# NB: Our production code depends on `pytest-cov` which indirectly depends on `coverage`, but in
# this test we have a direct dependency on `coverage` in order to load data files and test that
# coverage is collected by `pytest-cov` and has expected values. Unfortunately, `pytest-cov` has a
# floating dependency on `coverage` and `coverage` has changed its data file format in the past (eg:
# https://pypi.org/project/coverage/5.0a2/). If the default data format differs between `coverage`
# float and `coverage` pinned, we'll fail to read coverage data here in this test. We work around
# this by adding a pinned `coverage` requirement that matches our test dependency to the
# `PytestPrep` production requirements here.
class PytestPrepCoverageVersionPinned(PytestPrep):
  def extra_requirements(self):
    extra_reqs = list(super(PytestPrepCoverageVersionPinned, self).extra_requirements())
    extra_reqs.append('coverage=={}'.format(coverage.__version__))
    return extra_reqs


class PytestTestBase(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    return PytestRun

  _CONFTEST_CONTENT = '# I am an existing root-level conftest file.'

  def run_tests(self, targets, *passthru_args, **options):
    """Run the tests in the specified targets, with the specified PytestRun task options."""
    context = self._prepare_test_run(targets, *passthru_args, **options)
    self._do_run_tests(context)
    return context

  def run_failing_tests(self, targets, failed_targets, *passthru_args, **options):
    context = self._prepare_test_run(targets, *passthru_args, **options)
    with self.assertRaises(ErrorWhileTesting) as cm:
      self._do_run_tests(context)
    self.assertEqual(set(failed_targets), set(cm.exception.failed_targets))
    return context

  def try_run_tests(self, targets, *passthru_args, **options):
    try:
      self.run_tests(targets, *passthru_args, **options)
      return []
    except ErrorWhileTesting as e:
      return e.failed_targets

  def _prepare_test_run(self, targets, *passthru_args, **options):
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
    pp_task_type = self.synthesize_task_subtype(PytestPrepCoverageVersionPinned, 'pp_scope')
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

    # Targets under test.
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
      'python_library(name = "core", sources = ["core.py"])',
    )

    self.create_file(
        'app/app.py',
        dedent("""
          import core          # line 1
                               # line 2
                               # line 3
          def use_two():       # line 4
            return core.two()  # line 5
        """).strip())
    self.add_to_build_file(
      'app',
      'python_library(name = "app", sources = ["app.py"], dependencies = ["lib:core"])'
    )

    # Test targets.
    self.create_file(
        'tests/test_app.py',
        dedent("""
          import unittest

          import app

          class AppTest(unittest.TestCase):
            def test_use_two(self):
              self.assertEqual(2, app.use_two())
        """))
    self.add_to_build_file(
      'tests',
      'python_tests(name = "app", sources = ["test_app.py"], dependencies = ["app"])\n'
    )

    for name in ['green', 'green2', 'green3', 'red', 'red_in_class']:
      content = '''python_tests(
  name = "{name}",
  sources = ["test_core_{name}.py"],
  dependencies = ["lib:core"],
  coverage = ["core"],
)
'''.format(name=name)
      self.add_to_build_file('tests', content)

    self.add_to_build_file(
      'tests',
      '''python_tests(
  name = "sleep_no_timeout",
  sources = ["test_core_sleep.py"],
  dependencies = ["lib:core"],
  coverage = ["core"],
  timeout = 0,
)

python_tests(
  name = "sleep_timeout",
  sources = ["test_core_sleep.py"],
  dependencies = ["lib:core"],
  coverage = ["core"],
  timeout = 1,
)

python_tests(
  name = "error",
  sources = ["test_error.py"],
)

python_tests(
  name = "failure_outside_function",
  sources = ["test_failure_outside_function.py"],
)

python_tests(
  name = "green-with-conftest",
  sources = ["conftest.py", "test_core_green.py"],
  dependencies = ["lib:core"],
)

python_tests(
  name = "all",
  sources = ["test_core_green.py", "test_core_red.py"],
  dependencies = ["lib:core"],
)

python_tests(
  name = "all-with-coverage",
  sources = ["test_core_green.py", "test_core_red.py"],
  dependencies = ["lib:core"],
  coverage = ["core"],
)
'''
    )

    self.create_file(
        'tests/test_core_green.py',
        dedent("""
          import unittest

          import core

          class CoreGreenTest(unittest.TestCase):
            def test_one(self):
              self.assertEqual(1, core.one())
        """))

    self.create_file(
        'tests/test_core_green2.py',
        dedent("""
          import unittest

          import core

          class CoreGreen2Test(unittest.TestCase):
            def test_one(self):
              self.assertEqual(1, core.one())
        """))

    self.create_file(
        'tests/test_core_green3.py',
        dedent("""
          import unittest

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
          import unittest

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
        """))

    self.create_file(
        'tests/test_failure_outside_function.py',
        dedent("""
        def null():
          pass

        assert(False)
        """))

    self.create_file('tests/conftest.py', self._CONFTEST_CONTENT)

    self.app = self.target('tests:app')
    self.green = self.target('tests:green')
    self.green2 = self.target('tests:green2')
    self.green3 = self.target('tests:green3')
    self.red = self.target('tests:red')
    self.red_in_class = self.target('tests:red_in_class')
    self.sleep_no_timeout = self.target('tests:sleep_no_timeout')
    self.sleep_timeout = self.target('tests:sleep_timeout')
    self.error = self.target('tests:error')
    self.failure_outside_function = self.target('tests:failure_outside_function')
    self.green_with_conftest = self.target('tests:green-with-conftest')
    self.all = self.target('tests:all')
    self.all_with_cov = self.target('tests:all-with-coverage')

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
                           fast=True)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_fail_fast_skips_second_red_test_with_isolated_chroots(self):
    self.run_failing_tests(targets=[self.red, self.red_in_class],
                           failed_targets=[self.red],
                           fail_fast=True,
                           fast=False)

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

  def load_coverage_data(self, context, expect_coverage=True):
    path = os.path.join(self.build_root, 'lib', 'core.py')
    return self.load_coverage_data_for(context, path, expect_coverage=expect_coverage)

  def load_coverage_data_for(self, context, covered_path, expect_coverage=True):
    data_file = self.coverage_data_file()
    self.assertEqual(expect_coverage, os.path.isfile(data_file))
    if expect_coverage:
      python_sources = context.products.get_data(GatherSources.PYTHON_SOURCES)
      covered_relpath = os.path.relpath(covered_path, self.build_root)
      owning_targets = [t for t in context.targets()
                        if covered_relpath in t.sources_relative_to_buildroot()]
      self.assertEqual(1, len(owning_targets))
      owning_target = owning_targets[0]

      src_chroot_path = python_sources.path()
      src_root_abspath = os.path.join(self.build_root, owning_target.target_base)
      covered_src_root_relpath = os.path.relpath(covered_path, src_root_abspath)
      chroot_path = os.path.join(src_chroot_path, covered_src_root_relpath)

      cp = configparser.SafeConfigParser()
      src_to_target_base = {src: tgt.target_base
                            for tgt in context.targets()
                            for src in tgt.sources_relative_to_source_root()}

      PytestRun._add_plugin_config(cp,
                                   src_chroot_path=src_chroot_path,
                                   src_to_target_base=src_to_target_base)
      with temporary_file() as fp:
        cp.write(fp)
        fp.close()

        coverage_data = coverage.coverage(config_file=fp.name, data_file=data_file)
        coverage_data.load()

      _, all_statements, not_run_statements, _ = coverage_data.analysis(chroot_path)
      return all_statements, not_run_statements

  def run_coverage_auto(self,
                        targets,
                        failed_targets=None,
                        expect_coverage=True,
                        covered_path=None):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))
    simple_coverage_kwargs = {'coverage': 'auto'}
    if failed_targets:
      context = self.run_failing_tests(targets=targets,
                                       failed_targets=failed_targets,
                                       **simple_coverage_kwargs)
    else:
      context = self.run_tests(targets=targets, **simple_coverage_kwargs)

    if covered_path:
      return self.load_coverage_data_for(context, covered_path, expect_coverage=expect_coverage)
    else:
      return self.load_coverage_data(context, expect_coverage=expect_coverage)

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_coverage_auto_option_green(self):
    all_statements, not_run_statements = self.run_coverage_auto(targets=[self.green])
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([6], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_coverage_auto_option_red(self):
    all_statements, not_run_statements = self.run_coverage_auto(targets=[self.red],
                                                                failed_targets=[self.red])
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([2], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_coverage_auto_option_mixed_multiple_targets(self):
    all_statements, not_run_statements = self.run_coverage_auto(targets=[self.green, self.red],
                                                                failed_targets=[self.red])
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_coverage_auto_option_mixed_single_target(self):
    all_statements, not_run_statements = self.run_coverage_auto(targets=[self.all_with_cov],
                                                                failed_targets=[self.all_with_cov])
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_coverage_auto_option_no_explicit_coverage(self):
    init_subsystem(Target.Arguments)
    init_subsystem(SourceRootConfig)

    self.add_to_build_file('src/python/util', 'python_library()')

    self.create_file(
      'src/python/util/math.py',
      dedent("""
          def one():  # line 1
            return 1  # line 2
        """).strip())

    self.add_to_build_file('test/python/util', 'python_tests(dependencies = ["src/python/util"])')

    self.create_file(
      'test/python/util/test_math.py',
      dedent("""
          import unittest

          from util import math

          class MathTest(unittest.TestCase):
            def test_one(self):
              self.assertEqual(1, math.one())
        """))
    test = self.target('test/python/util')
    covered_path = os.path.join(self.build_root, 'src/python/util/math.py')

    all_statements, not_run_statements = self.run_coverage_auto(targets=[test],
                                                                covered_path=covered_path)
    self.assertEqual([1, 2], all_statements)
    self.assertEqual([], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_coverage_auto_option_no_explicit_coverage_idiosyncratic_layout(self):
    # The all target has no coverage attribute and the code under test does not follow the
    # auto-discover (parallel packages) pattern so we should get no coverage.
    init_subsystem(Target.Arguments)
    init_subsystem(SourceRootConfig)

    self.add_to_build_file('src/python/util', 'python_library()')

    self.create_file(
      'src/python/util/math.py',
      dedent("""
          def one():  # line 1
            return 1  # line 2
        """).strip())

    self.add_to_build_file('test/python/util_tests', 'python_tests(dependencies = ["src/python/util"])')

    self.create_file(
      'test/python/util_tests/test_math.py',
      dedent("""
          import unittest

          from util import math

          class MathTest(unittest.TestCase):
            def test_one(self):
              self.assertEqual(1, math.one())
        """))
    test = self.target('test/python/util_tests')
    covered_path = os.path.join(self.build_root, 'src/python/util/math.py')
    all_statements, not_run_statements = self.run_coverage_auto(targets=[test],
                                                                covered_path=covered_path)
    self.assertEqual([1, 2], all_statements)
    self.assertEqual([1, 2], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_coverage_auto_option_no_explicit_coverage_idiosyncratic_layout_no_packages(self):
    # The all target has no coverage attribute and the code under test does not follow the
    # auto-discover pattern so we should get no coverage. Additionally, the all target sources
    # live in the root package (they are top-level files); so they don't even have a package to use
    # to guess the code under test with; as such, we should not specify and coverage sources at all,
    # short-circuiting coverage.
    self.run_coverage_auto(targets=[self.all], failed_targets=[self.all], expect_coverage=False)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_coverage_modules_dne_option(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    # Explicit modules should trump .coverage.
    context = self.run_failing_tests(targets=[self.green, self.red], failed_targets=[self.red],
                                     coverage='does_not_exist,nor_does_this')
    all_statements, not_run_statements = self.load_coverage_data(context)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([1, 2, 5, 6], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_coverage_modules_option(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    context = self.run_failing_tests(targets=[self.all], failed_targets=[self.all], coverage='core')
    all_statements, not_run_statements = self.load_coverage_data(context)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=0)
  def test_coverage_paths_option(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    context = self.run_failing_tests(targets=[self.all], failed_targets=[self.all], coverage='lib/')
    all_statements, not_run_statements = self.load_coverage_data(context)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_coverage_issue_5314_primary_source_root(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    context = self.run_tests(targets=[self.app], coverage='app')

    app_path = os.path.join(self.build_root, 'app', 'app.py')
    all_statements, not_run_statements = self.load_coverage_data_for(context, app_path)
    self.assertEqual([1, 4, 5], all_statements)
    self.assertEqual([], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_coverage_issue_5314_secondary_source_root(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    context = self.run_tests(targets=[self.app], coverage='core')

    core_path = os.path.join(self.build_root, 'lib', 'core.py')
    all_statements, not_run_statements = self.load_coverage_data_for(context, core_path)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([2], not_run_statements)

  @ensure_cached(PytestRun, expected_num_artifacts=1)
  def test_coverage_issue_5314_all_source_roots(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))

    context = self.run_tests(targets=[self.app], coverage='app,core')

    app_path = os.path.join(self.build_root, 'app', 'app.py')
    all_statements, not_run_statements = self.load_coverage_data_for(context, app_path)
    self.assertEqual([1, 4, 5], all_statements)
    self.assertEqual([], not_run_statements)

    core_path = os.path.join(self.build_root, 'lib', 'core.py')
    all_statements, not_run_statements = self.load_coverage_data_for(context, core_path)
    self.assertEqual([1, 2, 5, 6], all_statements)
    self.assertEqual([2], not_run_statements)

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

  @contextmanager
  def marking_tests(self):
    init_subsystem(Target.Arguments)
    init_subsystem(SourceRootConfig)

    with temporary_dir() as marker_dir:
      self.create_file(
        'test/python/passthru/test_passthru.py',
        dedent("""
            import inspect
            import os
            import pytest
            import unittest
  
  
            class PassthruTest(unittest.TestCase):
              def touch(self, path):
                with open(path, 'wb') as fp:
                  fp.close()
                  
              def mark_test_run(self):
                caller_frame_record = inspect.stack()[1]
                
                # For the slot breakdown of a frame record tuple, see:
                #   https://docs.python.org/2/library/inspect.html#the-interpreter-stack
                _, _, _, caller_func_name, _, _ = caller_frame_record
                
                marker_file = os.path.join({marker_dir!r}, caller_func_name)
                self.touch(marker_file)
  
              def test_one(self):
                self.mark_test_run()
  
              @pytest.mark.purple
              def test_two(self):
                self.mark_test_run()
  
              def test_three(self):
                self.mark_test_run()
                
              @pytest.mark.red
              def test_four(self):
                self.mark_test_run()
              
              @pytest.mark.green
              def test_five(self):
                self.mark_test_run()                
          """.format(marker_dir=marker_dir)))

      def assert_mark(exists, name):
        message = '{} {!r} to be executed.'.format('Expected' if exists else 'Did not expect', name)
        marker_file = os.path.join(marker_dir, name)
        self.assertEqual(exists, os.path.exists(marker_file), message)

      self.add_to_build_file('test/python/passthru', 'python_tests()')
      test = self.target('test/python/passthru')
      yield test, functools.partial(assert_mark, True), functools.partial(assert_mark, False)

  def test_passthrough_args_facility_single_style(self):
    with self.marking_tests() as (target, assert_test_run, assert_test_not_run):
      self.run_tests([target], '-ktest_one or test_two')
      assert_test_run('test_one')
      assert_test_run('test_two')
      assert_test_not_run('test_three')
      assert_test_not_run('test_four')
      assert_test_not_run('test_five')

  def test_passthrough_args_facility_plus_arg_style(self):
    with self.marking_tests() as (target, assert_test_run, assert_test_not_run):
      self.run_tests([target], '-m', 'purple or red')
      assert_test_not_run('test_one')
      assert_test_run('test_two')
      assert_test_not_run('test_three')
      assert_test_run('test_four')
      assert_test_not_run('test_five')

  def test_passthrough_added_after_options(self):
    with self.marking_tests() as (target, assert_test_run, assert_test_not_run):
      self.run_tests([target], '-m', 'purple or red', options=['-k', 'two'])
      assert_test_not_run('test_one')
      assert_test_run('test_two')
      assert_test_not_run('test_three')
      assert_test_not_run('test_four')
      assert_test_not_run('test_five')

  def test_options_shlexed(self):
    with self.marking_tests() as (target, assert_test_run, assert_test_not_run):
      self.run_tests([target], options=["-m 'purple or red'"])
      assert_test_not_run('test_one')
      assert_test_run('test_two')
      assert_test_not_run('test_three')
      assert_test_run('test_four')
      assert_test_not_run('test_five')
