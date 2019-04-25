# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JunitTestsIntegrationTest(PantsRunIntegrationTest):

  def _assert_output_for_class(self, workdir, classname):
    def get_outdir(basedir):
      return os.path.join(basedir, 'test', 'junit')

    def get_stdout_file(basedir):
      return os.path.join(basedir, '{}.out.txt'.format(classname))

    def get_stderr_file(basedir):
      return os.path.join(basedir, '{}.err.txt'.format(classname))

    outdir = get_outdir(os.path.join(get_buildroot(), 'dist'))
    self.assertTrue(os.path.exists(get_stdout_file(outdir)))
    self.assertTrue(os.path.exists(get_stderr_file(outdir)))

    legacy_outdir = get_outdir(workdir)
    self.assertFalse(os.path.exists(get_stdout_file(legacy_outdir)))
    self.assertFalse(os.path.exists(get_stderr_file(legacy_outdir)))

  def test_junit_test_custom_interpreter(self):
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir(
          ['test.junit',
           'examples/tests/java/org/pantsbuild/example/hello/greet',
           'examples/tests/scala/org/pantsbuild/example/hello/welcome'],
          workdir)
      self.assert_success(pants_run)

      self._assert_output_for_class(workdir=workdir,
                                    classname='org.pantsbuild.example.hello.greet.GreetingTest')
      self._assert_output_for_class(workdir=workdir,
                                    classname='org.pantsbuild.example.hello.welcome.WelSpec')

  def test_junit_test(self):
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          'testprojects/tests/scala/org/pantsbuild/testproject/empty'],
          workdir)
      self.assert_failure(pants_run)

  def test_junit_test_with_test_option_with_classname(self):
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir(
          ['test.junit',
           '--test=org.pantsbuild.example.hello.greet.GreetingTest',
           'examples/tests/java/org/pantsbuild/example/hello/greet',
           'examples/tests/scala/org/pantsbuild/example/hello/welcome'],
          workdir)
      self.assert_success(pants_run)
      self._assert_output_for_class(workdir=workdir,
                                    classname='org.pantsbuild.example.hello.greet.GreetingTest')

  def test_junit_test_requiring_cwd_fails_without_option_specified(self):
    pants_run = self.run_pants([
        'test',
        'testprojects/tests/java/org/pantsbuild/testproject/cwdexample',
        '--python-setup-interpreter-constraints=CPython>=2.7,<3',
        '--python-setup-interpreter-constraints=CPython>=3.3',
        '--jvm-test-junit-options=-Dcwd.test.enabled=true'])
    self.assert_failure(pants_run)

  def test_junit_test_requiring_cwd_passes_with_option_with_value_specified(self):
    pants_run = self.run_pants([
        'test',
        'testprojects/tests/java/org/pantsbuild/testproject/cwdexample',
        '--python-setup-interpreter-constraints=CPython>=2.7,<3',
        '--python-setup-interpreter-constraints=CPython>=3.3',
        '--jvm-test-junit-options=-Dcwd.test.enabled=true',
        '--no-test-junit-chroot',
        '--test-junit-cwd=testprojects/src/java/org/pantsbuild/testproject/cwdexample/subdir'])
    self.assert_success(pants_run)

  def test_junit_test_requiring_cwd_fails_with_option_with_no_value_specified(self):
    pants_run = self.run_pants([
        'test',
        'testprojects/tests/java/org/pantsbuild/testproject/cwdexample',
        '--python-setup-interpreter-constraints=CPython>=2.7,<3',
        '--python-setup-interpreter-constraints=CPython>=3.3',
        '--jvm-test-junit-options=-Dcwd.test.enabled=true'])
    self.assert_failure(pants_run)

  def test_junit_test_early_exit(self):
    pants_run = self.run_pants([
        'test',
        'testprojects/src/java/org/pantsbuild/testproject/junit/earlyexit:tests'])
    self.assert_failure(pants_run)
    self.assertIn('java.lang.UnknownError: Abnormal VM exit - test crashed.', pants_run.stdout_data)
    self.assertIn('Tests run: 0,  Failures: 1', pants_run.stdout_data)
    self.assertIn('FATAL: VM exiting unexpectedly.', pants_run.stdout_data)

  def test_junit_test_target_cwd(self):
    pants_run = self.run_pants([
        'test',
        'testprojects/tests/java/org/pantsbuild/testproject/workdirs/onedir'])
    self.assert_success(pants_run)

  def test_junit_test_annotation_processor(self):
    pants_run = self.run_pants([
        'test',
        'testprojects/tests/java/org/pantsbuild/testproject/annotation'])
    self.assert_success(pants_run)

  def test_junit_test_256_failures(self):
    pants_run = self.run_pants([
      'test',
      'testprojects/tests/java/org/pantsbuild/testproject/fail256'])
    self.assert_failure(pants_run)
    self.assertIn('Failures: 256', pants_run.stdout_data)

  def test_junit_test_duplicate_resources(self):
    pants_run = self.run_pants([
        'test',
        'testprojects/maven_layout/junit_resource_collision'])
    self.assert_success(pants_run)

  def test_junit_test_target_cwd_overrides_option(self):
    pants_run = self.run_pants([
        'test',
        'testprojects/tests/java/org/pantsbuild/testproject/workdirs/onedir',
        '--no-test-junit-chroot',
        '--test-junit-cwd=testprojects/tests/java/org/pantsbuild/testproject/dummies'])
    self.assert_success(pants_run)

  def test_junit_test_failure_summary(self):
    with self.temporary_workdir() as workdir:
      failing_tree = 'testprojects/src/java/org/pantsbuild/testproject/junit/failing'
      with self.source_clone(failing_tree) as failing:
        failing_addr = os.path.join(failing, 'tests', 'org', 'pantsbuild', 'tmp', 'tests')
        pants_run = self.run_pants_with_workdir(['test.junit', '--failure-summary', failing_addr],
                                                workdir)
        self.assert_failure(pants_run)
        expected_groups = []
        expected_groups.append([
          'org/pantsbuild/tmp/tests:one',
          'org.pantsbuild.tmp.tests.OneTest#testSingle'
        ])
        expected_groups.append([
          'org/pantsbuild/tmp/tests:two',
          'org.pantsbuild.tmp.tests.TwoTest#testTupleFirst',
          'org.pantsbuild.tmp.tests.TwoTest#testTupleSecond',
        ])
        expected_groups.append([
          'org/pantsbuild/tmp/tests:three',
          'org.pantsbuild.tmp.tests.subtest.ThreeTest#testTripleFirst',
          'org.pantsbuild.tmp.tests.subtest.ThreeTest#testTripleSecond',
          'org.pantsbuild.tmp.tests.subtest.ThreeTest#testTripleThird',
        ])
        output = '\n'.join(line.strip() for line in pants_run.stdout_data.split('\n'))
        for group in expected_groups:
          self.assertIn('\n'.join(group), output)

  def test_junit_test_no_failure_summary(self):
    with self.temporary_workdir() as workdir:
      failing_tree = 'testprojects/src/java/org/pantsbuild/testproject/junit/failing'
      with self.source_clone(failing_tree) as failing:
        failing_addr = os.path.join(failing, 'tests', 'org', 'pantsbuild', 'tmp', 'tests')
        pants_run = self.run_pants_with_workdir(['test.junit',
                                                 '--no-failure-summary',
                                                 failing_addr],
                                                workdir)
        self.assert_failure(pants_run)
        output = '\n'.join(line.strip() for line in pants_run.stdout_data.split('\n'))
        self.assertNotIn('org/pantsbuild/tmp/tests:three\n'
                         'org.pantsbuild.tmp.tests.subtest.ThreeTest#testTripleFirst',
                         output)

  def test_junit_test_successes_and_failures(self):
    with self.temporary_workdir() as workdir:
      mixed_tree = 'testprojects/src/java/org/pantsbuild/testproject/junit/mixed'
      with self.source_clone(mixed_tree) as mixed:
        mixed_addr = os.path.join(mixed, 'tests', 'org', 'pantsbuild', 'tmp', 'tests')
        pants_run = self.run_pants_with_workdir(['test.junit',
                                                 '--failure-summary',
                                                 '--no-fail-fast',
                                                 mixed_addr],
                                                workdir)
        group = [
            'org/pantsbuild/tmp/tests',
            'org.pantsbuild.tmp.tests.AllTests#test1Failure',
            'org.pantsbuild.tmp.tests.AllTests#test3Failure',
            'org.pantsbuild.tmp.tests.AllTests#test4Error',
            'org.pantsbuild.tmp.tests.InnerClassTests$InnerClassFailureTest#testInnerFailure',
            'org.pantsbuild.tmp.tests.InnerClassTests$InnerInnerTest$InnerFailureTest#testFailure']
        output = '\n'.join(line.strip() for line in pants_run.stdout_data.split('\n'))
        self.assertIn('\n'.join(group), output,
                      '{group}\n not found in\n\n{output}.'.format(group='\n'.join(group),
                                                                   output=output))
        self.assertNotIn('org.pantsbuild.tmp.tests.AllTests#test2Success', output)
        self.assertNotIn('org.pantsbuild.tmp.tests.AllTestsBase', output)
        self.assertNotIn('org.pantsbuild.tmp.tests.AllTests$InnerClassSuccessTest', output)
