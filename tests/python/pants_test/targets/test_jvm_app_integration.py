# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestJvmAppIntegrationTest(PantsRunIntegrationTest):

  def test_bundle(self):
    """Default bundle with --no-deployjar.

    Verify synthetic jar contains only a manifest file and the rest bundle contains
    other library jars.
    """
    self.assertEquals(
      'Hello, world.\n',
      self.bundle_and_run(
        'testprojects/src/java/org/pantsbuild/testproject/bundle',
        'bundle-example',
        # this is the only thing bundle jar has, which means Class-Path must be properly
        # set for its Manifest.
        expected_bundle_jar_content=[
          'META-INF/MANIFEST.MF'
        ],
        expected_bundle_content=[
          'bundle-example.jar',
          'libs/com.google.guava-guava-18.0.jar',
          'libs/testprojects.src.java.org.pantsbuild.testproject.bundle.bundle-bin/0-z.jar']))

  def test_bundle_deployjar(self):
    """bundle with --deployjar.

    Verify monolithic jar is created with manifest file and the library class.
    """
    self.assertEquals(
      'Hello, world.\n',
      self.bundle_and_run(
        'testprojects/src/java/org/pantsbuild/testproject/bundle',
        'bundle-example',
        bundle_options=['--deployjar'],
        # this is the only thing bundle zip has, all class files must be there.
        expected_bundle_content=[
          'bundle-example.jar']))

  def test_missing_files(self):
    pants_run = self.run_pants(['bundle',
                                'testprojects/src/java/org/pantsbuild/testproject/bundle:missing-files'])
    self.assert_failure(pants_run)
