# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ClassmapTaskIntegrationTest(PantsRunIntegrationTest):
  # A test target with both transitive internal dependency as well as external dependency
  TEST_JVM_TARGET = 'testprojects/tests/java/org/pantsbuild/testproject/testjvms:seven'
  INTERNAL_MAPPING = ('org.pantsbuild.testproject.testjvms.TestSeven '
                      'testprojects/tests/java/org/pantsbuild/testproject/testjvms:seven')
  INTERNAL_TRANSITIVE_MAPPING = ('org.pantsbuild.testproject.testjvms.TestBase '
                                 'testprojects/tests/java/org/pantsbuild/testproject/testjvms:base')
  EXTERNAL_MAPPING = ('org.junit.ClassRule 3rdparty:junit')

  UNICODE_TEST_TARGET = 'testprojects/src/java/org/pantsbuild/testproject/unicode/cucumber'
  UNICODE_MAPPING = 'cucumber.api.java.zh_cn.假如 3rdparty:cucumber-java'

  def test_classmap_none(self):
    pants_run = self.do_command('classmap', success=True)
    self.assertEqual(len(pants_run.stdout_data.strip().split()), 0)

  def test_classmap(self):
    pants_run = self.do_command('classmap', self.TEST_JVM_TARGET, success=True)
    self.assertIn(self.INTERNAL_MAPPING, pants_run.stdout_data)
    self.assertIn(self.INTERNAL_TRANSITIVE_MAPPING, pants_run.stdout_data)
    self.assertIn(self.EXTERNAL_MAPPING, pants_run.stdout_data)

  def test_classmap_internal_only(self):
    pants_run = self.do_command('classmap', '--internal-only', self.TEST_JVM_TARGET, success=True)
    self.assertIn(self.INTERNAL_MAPPING, pants_run.stdout_data)
    self.assertIn(self.INTERNAL_TRANSITIVE_MAPPING, pants_run.stdout_data)
    self.assertNotIn(self.EXTERNAL_MAPPING, pants_run.stdout_data)

  def test_classmap_intransitive(self):
    pants_run = self.do_command('classmap', '--no-transitive', self.TEST_JVM_TARGET, success=True)
    self.assertIn(self.INTERNAL_MAPPING, pants_run.stdout_data)
    self.assertNotIn(self.INTERNAL_TRANSITIVE_MAPPING, pants_run.stdout_data)
    self.assertNotIn(self.EXTERNAL_MAPPING, pants_run.stdout_data)

  def test_classmap_unicode(self):
    pants_run = self.do_command('classmap', self.UNICODE_TEST_TARGET, success=True)
    self.assertIn(self.UNICODE_MAPPING, pants_run.stdout_data)
