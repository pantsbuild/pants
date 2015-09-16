# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BinaryCreateIntegrationTest(PantsRunIntegrationTest):

  def test_autovalue_isolated_classfiles(self):
    self.build_and_run(
      pants_args=['binary', '--compile-java-strategy=isolated',
                  'examples/src/java/org/pantsbuild/example/autovalue'],
      rel_out_path='dist',
      java_args=['-jar', 'autovalue.jar'],
      expected_output='Hello Autovalue!'
    )

  def test_manifest_entries(self):
    self.build_and_run(
      pants_args=['binary',
                  'testprojects/src/java/org/pantsbuild/testproject/manifest:manifest-with-source'],
      rel_out_path='dist',
      java_args=['-cp', 'manifest-with-source.jar', 'org.pantsbuild.testproject.manifest.Manifest'],
      expected_output='Hello World!  Version: 1.2.3'
    )

  def test_manifest_entries_no_source(self):
    self.build_and_run(
      pants_args=['binary',
                  'testprojects/src/java/org/pantsbuild/testproject/manifest:manifest-no-source'],
      rel_out_path='dist',
      java_args=['-cp', 'manifest-no-source.jar', 'org.pantsbuild.testproject.manifest.Manifest'],
      expected_output='Hello World!  Version: 4.5.6',
    )

  def test_manifest_entries_bundle(self):
    self.build_and_run(
      pants_args=['bundle',
                  'testprojects/src/java/org/pantsbuild/testproject/manifest:manifest-app'],
      rel_out_path=os.path.join('dist', 'manifest-app-bundle'),
      java_args=['-cp', 'manifest-no-source.jar', 'org.pantsbuild.testproject.manifest.Manifest'],
      expected_output='Hello World!  Version: 4.5.6',
    )

  def build_and_run(self, pants_args, rel_out_path, java_args, expected_output):
    self.assert_success(self.run_pants(['clean-all']))
    pants_run = self.run_pants(pants_args, {})
    self.assert_success(pants_run)

    out_path = os.path.join(get_buildroot(), rel_out_path)
    java_run = subprocess.Popen(['java'] + java_args, stdout=subprocess.PIPE, cwd=out_path)
    java_retcode = java_run.wait()
    java_out = java_run.stdout.read()
    self.assertEquals(java_retcode, 0)
    self.assertIn(expected_output, java_out)
