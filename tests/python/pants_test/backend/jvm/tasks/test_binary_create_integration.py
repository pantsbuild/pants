# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

import pytest

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_delete
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BinaryCreateIntegrationTest(PantsRunIntegrationTest):

  def test_autovalue_classfiles(self):
    self.build_and_run(
      pants_args=['binary', 'examples/src/java/org/pantsbuild/example/autovalue'],
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

  # This test passes as of 0.0.51, but fails in subsequent releases with guava being
  # bundled in the resulting .jar
  @pytest.mark.xfail
  def test_deploy_excludes(self):
    jar_filename = os.path.join('dist', 'deployexcludes.jar')
    safe_delete(jar_filename)
    pants_run = self.run_pants(['binary',
                  'testprojects/src/java/org/pantsbuild/testproject/deployexcludes'], {})
    self.assert_success(pants_run)
    # The resulting binary should not contain any guava classes
    with open_zip(jar_filename) as jar_file:
      self.assertEquals({'META-INF/',
                         'META-INF/MANIFEST.MF',
                         'org/',
                         'org/pantsbuild/',
                         'org/pantsbuild/testproject/',
                         'org/pantsbuild/testproject/deployexcludes/',
                         'org/pantsbuild/testproject/deployexcludes/DeployExcludesMain.class'},
                        set(jar_file.namelist()))

    # This jar should not run by itself, missing symbols
    java_run = subprocess.Popen(['java', '-jar', jar_filename], stderr=subprocess.PIPE)
    java_retcode = java_run.wait()
    java_stderr = java_run.stderr.read()
    self.assertEquals(java_retcode, 1)
    self.assertIn("java.lang.NoClassDefFoundError: com/google/common/collect/ImmutableSortedSet", java_stderr)

    java_run = subprocess.Popen([
      'java', '-cp',
      jar_filename + ':' + '.pants.d/ivy/jars/com.google.guava/guava/bundles/guava-18.0.jar',
      'org.pantsbuild.testproject.deployexcludes.DeployExcludesMain'],
      stdout=subprocess.PIPE)
    java_retcode = java_run.wait()
    java_stdout = java_run.stdout.read()
    self.assertEquals(java_retcode, 0)
    self.assertIn("DeployExcludes Hello World", java_stdout)

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
