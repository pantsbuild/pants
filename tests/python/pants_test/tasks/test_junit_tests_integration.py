# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager
from textwrap import dedent
from xml.etree import ElementTree

import pytest

from pants.util.contextutil import temporary_dir
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

  def test_junit_test_suppress_output_flag(self):
    pants_run = self.run_pants([
        'test.junit',
        '--no-suppress-output',
        'testprojects/tests/java/org/pantsbuild/testproject/dummies:passing_target'])
    self.assertIn('Hello from test1!', pants_run.stdout_data)
    self.assertIn('Hello from test2!', pants_run.stdout_data)

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

  @contextmanager
  def _failing_test_cases(self):
    with temporary_dir(root_dir=self.workdir_root()) as source_dir:
      with open(os.path.join(source_dir, 'BUILD'), 'w+') as f:
        f.write('source_root("{}/tests")\n'.format(os.path.basename(source_dir)))
      tests_dir = os.path.join(source_dir, 'tests')
      subpath = os.path.join('org', 'pantsbuild', 'tmp', 'tests')
      tests_subdir = os.path.join(tests_dir, subpath)
      os.makedirs(tests_subdir)
      with open(os.path.join(tests_subdir, 'BUILD'), 'w+') as f:
        f.write(dedent('''
          target(name='tests',
            dependencies=[
              ':one',
              ':two',
              ':three',
            ],
          )

          java_library(name='base',
            dependencies=['3rdparty:junit'],
          )

          java_tests(name='one',
            sources=['OneTest.java'],
            dependencies=[':base'],
          )

          java_tests(name='two',
            sources=['TwoTest.java'],
            dependencies=[':base'],
          )

          java_tests(name='three',
            sources=['subtest/ThreeTest.java'],
            dependencies=[':base'],
          )
        '''))
      with open(os.path.join(tests_subdir, 'OneTest.java'), 'w+') as f:
        f.write(dedent('''
          package org.pantsbuild.tmp.tests;

          import org.junit.Test;
          import static org.junit.Assert.*;

          public class OneTest {
            @Test
            public void testSingle() {
              assertTrue("Single is false.", false);
            }
          }
        '''))
      with open(os.path.join(tests_subdir, 'TwoTest.java'), 'w+') as f:
        f.write(dedent('''
          package org.pantsbuild.tmp.tests;

          import org.junit.Test;
          import static org.junit.Assert.*;

          public class TwoTest {
            @Test
            public void testTupleFirst() {
              assertTrue("First is false.", false);
            }

            @Test
            public void testTupleSecond() {
              assertTrue("Second is false.", false);
            }
          }
        '''))
      os.makedirs(os.path.join(tests_subdir, 'subtest'))
      with open(os.path.join(tests_subdir, 'subtest', 'ThreeTest.java'), 'w+') as f:
        f.write(dedent('''
          package org.pantsbuild.tmp.tests.subtest;

          import org.junit.Test;
          import static org.junit.Assert.*;

          public class ThreeTest {
            @Test
            public void testTripleFirst() {
              assertTrue("First is false.", false);
            }

            @Test
            public void testTripleSecond() {
              assertTrue("Second is false.", false);
            }

            @Test
            public void testTripleThird() {
              assertTrue("Third is false.", false);
            }
          }
        '''))
      yield tests_subdir

  @contextmanager
  def _mixed_test_cases(self):
    with temporary_dir(root_dir=self.workdir_root()) as source_dir:
      with open(os.path.join(source_dir, 'BUILD'), 'w+') as f:
        f.write('source_root("{}/tests")\n'.format(os.path.basename(source_dir)))
      tests_dir = os.path.join(source_dir, 'tests')
      subpath = os.path.join('org', 'pantsbuild', 'tmp', 'tests')
      tests_subdir = os.path.join(tests_dir, subpath)
      os.makedirs(tests_subdir)
      with open(os.path.join(tests_subdir, 'BUILD'), 'w+') as f:
        f.write(dedent('''
          java_tests(name='tests',
            sources=['AllTests.java'],
            dependencies=['3rdparty:junit'],
          )
        '''))
      with open(os.path.join(tests_subdir, 'AllTests.java'), 'w+') as f:
        f.write(dedent('''
          package org.pantsbuild.tmp.tests;

          import org.junit.Test;
          import static org.junit.Assert.*;

          public class AllTests {

            @Test
            public void test1Failure() {
              assertTrue(false);
            }

            @Test
            public void test2Success() {
              assertTrue(true);
            }

            @Test
            public void test3Failure() {
              assertTrue(false);
            }

            @Test
            public void test4Error() {
              throw new RuntimeException();
            }
          }
        '''))
      yield tests_subdir

  def test_junit_test_failure_summary(self):
    with self.temporary_workdir() as workdir:
      with self._failing_test_cases() as tests_dir:
        pants_run = self.run_pants_with_workdir([
          'test',
          '--test-junit-failure-summary',
          os.path.relpath(tests_dir),
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
      with self._failing_test_cases() as tests_dir:
        pants_run = self.run_pants_with_workdir([
          'test',
          '--no-test-junit-failure-summary',
          os.path.relpath(tests_dir)
        ], workdir)
        self.assert_failure(pants_run)
        output = '\n'.join(line.strip() for line in pants_run.stdout_data.split('\n'))
        self.assertNotIn('org/pantsbuild/tmp/tests:three\n'
                         'org.pantsbuild.tmp.tests.subtest.ThreeTest#testTripleFirst',
                         output)

  def test_junit_test_successes_and_failures(self):
    with self.temporary_workdir() as workdir:
      with self._mixed_test_cases() as tests_dir:
        pants_run = self.run_pants_with_workdir([
          'test',
          '--test-junit-failure-summary',
          '--no-test-junit-fail-fast',
          os.path.relpath(tests_dir),
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
