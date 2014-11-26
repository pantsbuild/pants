# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JunitTestsIntegrationTest(PantsRunIntegrationTest):

  def _assert_junit_output(self, workdir):
    self.assertTrue(os.path.exists(
      os.path.join(workdir, 'test', 'junit',
                   'com.pants.examples.hello.greet.GreetingTest.out.txt')))
    self.assertTrue(os.path.exists(
      os.path.join(workdir, 'test', 'junit',
                   'com.pants.examples.hello.greet.GreetingTest.err.txt')))
    self.assertTrue(os.path.exists(
      os.path.join(workdir, 'test', 'junit',
                   'com.pants.example.hello.welcome.WelSpec.out.txt')))
    self.assertTrue(os.path.exists(
      os.path.join(workdir, 'test', 'junit',
                   'com.pants.example.hello.welcome.WelSpec.err.txt')))

  def test_junit_test(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      pants_run = self.run_pants_with_workdir(
        ['goal', 'test', 'examples/tests/java/com/pants/examples/hello/greet',
         'examples/tests/scala/com/pants/example/hello/welcome',
         '--interpreter=CPython>=2.6,<3', '--interpreter=CPython>=3.3',
         '--print-exception-stacktrace', ],
        workdir)
      self.assert_success(pants_run)
      self._assert_junit_output(workdir)

  def test_junit_test_with_emma(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      pants_run = self.run_pants_with_workdir(
        ['goal', 'test', 'examples/tests/java//com/pants/examples/hello/greet',
         'examples/tests/scala/com/pants/example/hello/welcome',
         '--interpreter=CPython>=2.6,<3', '--interpreter=CPython>=3.3',
         '--test-junit-coverage-processor=emma', '--test-junit-coverage',
         '--test-junit-coverage-xml', '--test-junit-coverage-html',
         '--print-exception-stacktrace', ],
        workdir)
      self.assert_success(pants_run)
      self._assert_junit_output(workdir)
      # TODO(Eric Ayers): Why does  emma puts coverage.xml in a different directory from cobertura?
      self.assertTrue(os.path.exists(
        os.path.join(workdir, 'test', 'junit', 'coverage', 'coverage.xml')))
      self.assertTrue(os.path.exists(
        os.path.join(workdir, 'test', 'junit', 'coverage', 'html', 'index.html')))

    # Look for emma report in stdout_data:
    # 23:20:21 00:02       [emma-report][EMMA v2.1.5320 (stable) report, generated Mon Oct 13 ...
    self.assertIn('[emma-report]', pants_run.stdout_data)

    # See if the two test classes ended up generating data in the coverage report.
    lines = pants_run.stdout_data.split('\n')
    in_package_report = False
    package_report = ""
    for line in lines:
      if 'COVERAGE BREAKDOWN BY PACKAGE:' in line:
        in_package_report = True
      if in_package_report:
        package_report += line

    self.assertIn('com.pants.example.hello.welcome', package_report)
    self.assertIn('com.pants.examples.hello.greet', package_report)

  def test_junit_test_with_coberta(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      pants_run = self.run_pants_with_workdir(
        ['goal', 'test', 'examples/tests/java//com/pants/examples/hello/greet',
         'examples/tests/scala/com/pants/example/hello/welcome',
         '--interpreter=CPython>=2.6,<3',
         '--interpreter=CPython>=3.3',
         '--print-exception-stacktrace',
         '--test-junit-coverage-processor=cobertura', '--test-junit-coverage',
         '--test-junit-coverage-xml', '--test-junit-coverage-html',],
        workdir)
      self.assert_success(pants_run)
      self._assert_junit_output(workdir)

      self.assertTrue(os.path.exists(
        os.path.join(workdir, 'test', 'junit', 'coverage', 'html', 'index.html')))
      # TODO(Eric Ayers): Look at the xml report.  I think something is broken, it is empty
      self.assertTrue(os.path.exists(
        os.path.join(workdir, 'test', 'junit', 'coverage', 'xml', 'coverage.xml')))

  def test_junit_test_with_cwd(self):
    # Make sure the test fails if you don't specify cwd
    pants_run = self.run_pants([
      'goal', 'test', 'testprojects/tests/java/com/pants/testproject/cwdexample',
      '--interpreter=CPython>=2.6,<3', '--interpreter=CPython>=3.3',
      '--print-exception-stacktrace',
      '--test-junit-jvm-options=-Dcwd.test.enabled=true',])
    self.assert_failure(pants_run)

    # Expicit cwd specified
    pants_run = self.run_pants([
      'goal', 'test', 'testprojects/tests/java/com/pants/testproject/cwdexample',
      '--interpreter=CPython>=2.6,<3', '--interpreter=CPython>=3.3',
      '--print-exception-stacktrace',
      '--test-junit-jvm-options=-Dcwd.test.enabled=true',
      '--test-junit-cwd=testprojects/src/java/com/pants/testproject/cwdexample/subdir',])
    self.assert_success(pants_run)

    # Implicit cwd specified based on path to target
    pants_run = self.run_pants([
      'goal', 'test', 'testprojects/tests/java/com/pants/testproject/cwdexample',
      '--interpreter=CPython>=2.6,<3', '--interpreter=CPython>=3.3',
      '--print-exception-stacktrace',
      '--test-junit-jvm-options=-Dcwd.test.enabled=true',
      '--test-junit-cwd',])
    self.assert_success(pants_run)

