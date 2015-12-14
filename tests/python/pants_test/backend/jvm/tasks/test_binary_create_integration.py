# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

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
    # package level manifest entry, in this case, `Implementation-Version`, no longer work
    # because package files are not included in the bundle jar, instead they are referenced
    # through its manifest's Class-Path.
    self.build_and_run(
      pants_args=['bundle',
                  'testprojects/src/java/org/pantsbuild/testproject/manifest:manifest-app'],
      rel_out_path=os.path.join('dist', 'manifest-app-bundle'),
      java_args=['-cp', 'manifest-no-source.jar', 'org.pantsbuild.testproject.manifest.Manifest'],
      expected_output='Hello World!  Version: null',
    )

    # If we still want to get package level manifest entries, we need to include packages files
    # in the bundle jar through `--deployjar`. However use that with caution because the monolithic
    # jar may have multiple packages.
    self.build_and_run(
      pants_args=['bundle',
                  'testprojects/src/java/org/pantsbuild/testproject/manifest:manifest-app',
                  '--bundle-jvm-deployjar'],
      rel_out_path=os.path.join('dist', 'manifest-app-bundle'),
      java_args=['-cp', 'manifest-no-source.jar', 'org.pantsbuild.testproject.manifest.Manifest'],
      expected_output='Hello World!  Version: 4.5.6',
    )

  def test_deploy_excludes(self):
    jar_filename = os.path.join('dist', 'deployexcludes.jar')
    safe_delete(jar_filename)
    command = ['binary', 'testprojects/src/java/org/pantsbuild/testproject/deployexcludes']
    with self.pants_results(command) as pants_run:
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
      self.run_java(java_args=['-jar', jar_filename],
                    expected_returncode=1,
                    expected_output='java.lang.NoClassDefFoundError: '
                                    'com/google/common/collect/ImmutableSortedSet')

      # But adding back the deploy_excluded symbols should result in a clean run.
      classpath = [jar_filename,
                   os.path.join(pants_run.workdir,
                                'ivy/jars/com.google.guava/guava/bundles/guava-18.0.jar')]

      self.run_java(java_args=['-cp', os.pathsep.join(classpath),
                               'org.pantsbuild.testproject.deployexcludes.DeployExcludesMain'],
                    expected_output='DeployExcludes Hello World')

  def build_and_run(self, pants_args, rel_out_path, java_args, expected_output):
    self.assert_success(self.run_pants(['clean-all']))
    with self.pants_results(pants_args, {}) as pants_run:
      self.assert_success(pants_run)

      out_path = os.path.join(get_buildroot(), rel_out_path)
      self.run_java(java_args=java_args, expected_output=expected_output, cwd=out_path)

  def run_java(self, java_args, expected_returncode=0, expected_output=None, cwd=None):
    command = ['java'] + java_args
    process = subprocess.Popen(command,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               cwd=cwd)
    stdout, stderr = process.communicate()

    self.assertEquals(expected_returncode, process.returncode,
                      ('Expected exit code {} from command `{}` but got {}:\n'
                       'stdout:\n{}\n'
                       'stderr:\n{}'
                       .format(expected_returncode,
                               ' '.join(command),
                               process.returncode,
                               stdout,
                               stderr)))
    self.assertIn(expected_output, stdout if expected_returncode == 0 else stderr)
