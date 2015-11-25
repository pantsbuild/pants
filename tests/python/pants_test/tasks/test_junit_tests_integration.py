# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JunitTestsIntegrationTest(PantsRunIntegrationTest):

  def _assert_junit_output_exists_for_class(self, workdir, classname):
    self.assertTrue(os.path.exists(
      os.path.join(workdir, 'test', 'junit', '{}.out.txt'.format(classname))))
    self.assertTrue(os.path.exists(
      os.path.join(workdir, 'test', 'junit', '{}.err.txt'.format(classname))))

  def _assert_junit_output(self, workdir):
    self._assert_junit_output_exists_for_class(workdir, 'org.pantsbuild.example.hello.greet.GreetingTest')
    self._assert_junit_output_exists_for_class(workdir, 'org.pantsbuild.example.hello.welcome.WelSpec')

  def test_junit_test_custom_interpreter(self):
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          'examples/tests/java/org/pantsbuild/example/hello/greet',
          'examples/tests/scala/org/pantsbuild/example/hello/welcome',
          '--interpreter=CPython>=2.6,<3',
          '--interpreter=CPython>=3.3'],
          workdir)
      self.assert_success(pants_run)
      self._assert_junit_output(workdir)

  def test_junit_test(self):
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          'testprojects/tests/scala/org/pantsbuild/testproject/empty'],
          workdir)
      self.assert_failure(pants_run)

  def test_junit_test_with_test_option_with_relpath(self):
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          '--test-junit-test=examples/tests/java/org/pantsbuild/example/hello/greet/GreetingTest.java',
          'examples/tests/java/org/pantsbuild/example/hello/greet',
          'examples/tests/scala/org/pantsbuild/example/hello/welcome'],
          workdir)
      self.assert_success(pants_run)
      self._assert_junit_output_exists_for_class(workdir, 'org.pantsbuild.example.hello.greet.GreetingTest')

  def test_junit_test_with_test_option_with_dot_slash_relpath(self):
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          '--test-junit-test=./examples/tests/java/org/pantsbuild/example/hello/greet/GreetingTest.java',
          'examples/tests/java/org/pantsbuild/example/hello/greet',
          'examples/tests/scala/org/pantsbuild/example/hello/welcome'],
          workdir)
      self.assert_success(pants_run)
      self._assert_junit_output_exists_for_class(workdir, 'org.pantsbuild.example.hello.greet.GreetingTest')

  def test_junit_test_with_test_option_with_classname(self):
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          '--test-junit-test=org.pantsbuild.example.hello.greet.GreetingTest',
          'examples/tests/java/org/pantsbuild/example/hello/greet',
          'examples/tests/scala/org/pantsbuild/example/hello/welcome'],
          workdir)
      self.assert_success(pants_run)
      self._assert_junit_output_exists_for_class(workdir, 'org.pantsbuild.example.hello.greet.GreetingTest')

  def test_junit_test_requiring_cwd_fails_without_option_specified(self):
    pants_run = self.run_pants([
        'test',
        'testprojects/tests/java/org/pantsbuild/testproject/cwdexample',
        '--interpreter=CPython>=2.6,<3',
        '--interpreter=CPython>=3.3',
        '--jvm-test-junit-options=-Dcwd.test.enabled=true'])
    self.assert_failure(pants_run)

  def test_junit_test_requiring_cwd_passes_with_option_with_value_specified(self):
    pants_run = self.run_pants([
        'test',
        'testprojects/tests/java/org/pantsbuild/testproject/cwdexample',
        '--interpreter=CPython>=2.6,<3',
        '--interpreter=CPython>=3.3',
        '--jvm-test-junit-options=-Dcwd.test.enabled=true',
        '--test-junit-cwd=testprojects/src/java/org/pantsbuild/testproject/cwdexample/subdir'])
    self.assert_success(pants_run)

  def test_junit_test_requiring_cwd_fails_with_option_with_no_value_specified(self):
    pants_run = self.run_pants([
        'test',
        'testprojects/tests/java/org/pantsbuild/testproject/cwdexample',
        '--interpreter=CPython>=2.6,<3',
        '--interpreter=CPython>=3.3',
        '--jvm-test-junit-options=-Dcwd.test.enabled=true'])
    self.assert_failure(pants_run)

  def test_junit_test_deprecated_suppress_output_flag(self):
    pants_run = self.run_pants([
        'test.junit',
        '--no-suppress-output',
        'testprojects/tests/java/org/pantsbuild/testproject/dummies:passing_target'])
    self.assertIn('Hello from test1!', pants_run.stdout_data)
    self.assertIn('Hello from test2!', pants_run.stdout_data)

    pants_run = self.run_pants([
        'test.junit',
        '--suppress-output',
        'testprojects/tests/java/org/pantsbuild/testproject/dummies:passing_target'])
    self.assertNotIn('Hello from test1!', pants_run.stdout_data)
    self.assertNotIn('Hello from test2!', pants_run.stdout_data)

  def test_junit_test_output_flag(self):
    def run_test(output_mode):
      args = ['test.junit', '--no-test-junit-fail-fast']
      if output_mode is not None:
        args.append('--output-mode=' + output_mode)
      args.append('testprojects/src/java/org/pantsbuild/testproject/junit/suppressoutput:tests')
      return self.run_pants(args)

    run_with_all_output = run_test('ALL')
    self.assertIn('Failure output', run_with_all_output.stdout_data)
    self.assertIn('Success output', run_with_all_output.stdout_data)

    run_with_failure_only_output = run_test('FAILURE_ONLY')
    self.assertIn('Failure output', run_with_failure_only_output.stdout_data)
    self.assertNotIn('Success output', run_with_failure_only_output.stdout_data)

    run_with_none_output = run_test('NONE')
    self.assertNotIn('Failure output', run_with_none_output)
    self.assertNotIn('Success output', run_with_none_output)

    run_with_default_output = run_test(None)
    self.assertNotIn('Failure output', run_with_default_output)
    self.assertNotIn('Success output', run_with_default_output)

  def test_junit_test_target_cwd(self):
    pants_run = self.run_pants([
      'test',
      'testprojects/tests/java/org/pantsbuild/testproject/workdirs/onedir',
    ])
    self.assert_success(pants_run)

  def test_junit_test_annotation_processor(self):
    pants_run = self.run_pants([
      'test',
      'testprojects/tests/java/org/pantsbuild/testproject/annotation',
    ])
    self.assert_success(pants_run)

  def test_junit_test_duplicate_resources(self):
    pants_run = self.run_pants([
      'test',
      'testprojects/maven_layout/junit_resource_collision',
    ])
    self.assert_success(pants_run)

  def test_junit_test_target_cwd_overrides_option(self):
    pants_run = self.run_pants([
      'test',
      'testprojects/tests/java/org/pantsbuild/testproject/workdirs/onedir',
      '--test-junit-cwd=testprojects/tests/java/org/pantsbuild/testproject/dummies'
    ])
    self.assert_success(pants_run)

  def test_junit_test_failure_summary(self):
    with self.temporary_workdir() as workdir:
      with self.source_clone('testprojects/src/java/org/pantsbuild/testproject/junit/failing') as failing:
        pants_run = self.run_pants_with_workdir([
          'test',
          '--test-junit-failure-summary',
          os.path.join(failing, 'tests', 'org', 'pantsbuild', 'tmp', 'tests'),
        ], workdir)
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
      with self.source_clone('testprojects/src/java/org/pantsbuild/testproject/junit/failing') as failing:
        pants_run = self.run_pants_with_workdir([
          'test',
          '--no-test-junit-failure-summary',
          os.path.join(failing, 'tests', 'org', 'pantsbuild', 'tmp', 'tests')
        ], workdir)
        self.assert_failure(pants_run)
        output = '\n'.join(line.strip() for line in pants_run.stdout_data.split('\n'))
        self.assertNotIn('org/pantsbuild/tmp/tests:three\n'
                         'org.pantsbuild.tmp.tests.subtest.ThreeTest#testTripleFirst',
                         output)

  def test_junit_test_successes_and_failures(self):
    with self.temporary_workdir() as workdir:
      with self.source_clone('testprojects/src/java/org/pantsbuild/testproject/junit/mixed') as mixed:
        pants_run = self.run_pants_with_workdir([
          'test',
          '--test-junit-failure-summary',
          '--no-test-junit-fail-fast',
          os.path.join(mixed, 'tests', 'org', 'pantsbuild', 'tmp', 'tests'),
        ], workdir)
        group = [
          'org/pantsbuild/tmp/tests:tests',
          'org.pantsbuild.tmp.tests.AllTests#test1Failure',
          'org.pantsbuild.tmp.tests.AllTests#test3Failure',
          'org.pantsbuild.tmp.tests.AllTests#test4Error',
        ]
        output = '\n'.join(line.strip() for line in pants_run.stdout_data.split('\n'))
        self.assertIn('\n'.join(group), output,
                      '{group}\n not found in\n\n{output}.'.format(group='\n'.join(group),
                                                                   output=output))
