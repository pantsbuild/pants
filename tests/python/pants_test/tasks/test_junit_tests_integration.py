# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from xml.etree import ElementTree

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
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
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
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          'testprojects/tests/scala/org/pantsbuild/testproject/empty'],
          workdir)
      self.assert_failure(pants_run)

  def test_junit_test_with_test_option_with_relpath(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          '--test-junit-test=examples/tests/java/org/pantsbuild/example/hello/greet/GreetingTest.java',
          'examples/tests/java/org/pantsbuild/example/hello/greet',
          'examples/tests/scala/org/pantsbuild/example/hello/welcome'],
          workdir)
      self.assert_success(pants_run)
      self._assert_junit_output_exists_for_class(workdir, 'org.pantsbuild.example.hello.greet.GreetingTest')

  def test_junit_test_with_test_option_with_dot_slash_relpath(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          '--test-junit-test=./examples/tests/java/org/pantsbuild/example/hello/greet/GreetingTest.java',
          'examples/tests/java/org/pantsbuild/example/hello/greet',
          'examples/tests/scala/org/pantsbuild/example/hello/welcome'],
          workdir)
      self.assert_success(pants_run)
      self._assert_junit_output_exists_for_class(workdir, 'org.pantsbuild.example.hello.greet.GreetingTest')

  def test_junit_test_with_test_option_with_classname(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          '--test-junit-test=org.pantsbuild.example.hello.greet.GreetingTest',
          'examples/tests/java/org/pantsbuild/example/hello/greet',
          'examples/tests/scala/org/pantsbuild/example/hello/welcome'],
          workdir)
      self.assert_success(pants_run)
      self._assert_junit_output_exists_for_class(workdir, 'org.pantsbuild.example.hello.greet.GreetingTest')

  def test_junit_test_with_emma(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          'examples/tests/java//org/pantsbuild/example/hello/greet',
          'examples/tests/scala/org/pantsbuild/example/hello/welcome',
          '--interpreter=CPython>=2.6,<3',
          '--interpreter=CPython>=3.3',
          '--test-junit-coverage-processor=emma',
          '--test-junit-coverage',
          '--test-junit-coverage-xml',
          '--test-junit-coverage-html',
          '--test-junit-coverage-jvm-options=-Xmx1g',
          '--test-junit-coverage-jvm-options=-XX:MaxPermSize=256m'],
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

    self.assertIn('org.pantsbuild.example.hello.welcome', package_report)
    self.assertIn('org.pantsbuild.example.hello.greet', package_report)

  def test_junit_test_with_coberta(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      pants_run = self.run_pants_with_workdir([
          'test',
          'examples/tests/java//org/pantsbuild/example/hello/greet',
          'examples/tests/scala/org/pantsbuild/example/hello/welcome',
          '--interpreter=CPython>=2.6,<3',
          '--interpreter=CPython>=3.3',
          '--test-junit-coverage-processor=cobertura',
          '--test-junit-coverage',
          '--test-junit-coverage-xml',
          '--test-junit-coverage-html',
          '--test-junit-coverage-jvm-options=-Xmx1g',
          '--test-junit-coverage-jvm-options=-XX:MaxPermSize=256m'],
          workdir)
      self.assert_success(pants_run)
      self._assert_junit_output(workdir)

      self.assertTrue(os.path.exists(
        os.path.join(workdir, 'test', 'junit', 'coverage', 'html', 'index.html')))
      xmlf = os.path.join(workdir, 'test', 'junit', 'coverage', 'xml', 'coverage.xml')
      self.assertTrue(os.path.exists(xmlf))
      hits = ElementTree.parse(xmlf).findall("packages/package/classes/class/lines/line")
      if all(i.attrib['hits'] == "0" for i in hits):
        self.fail("no nonzero hits found in the generated coverage.xml")

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
      '--compile-java-strategy=isolated',
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
