# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

import pytest

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_rmtree
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.tasks.test_base import is_exe


def shared_artifacts(version, extra_jar=None):
  published_file_list = ['ivy-{0}.xml'.format(version),
                         'hello-greet-{0}.jar'.format(version),
                         'hello-greet-{0}.pom'.format(version),
                         'hello-greet-{0}-sources.jar'.format(version)]
  if extra_jar:
    published_file_list.append(extra_jar)
  return {'com/pants/testproject/publish/hello-greet/{0}/'.format(version): published_file_list}


def publish_extra_config(unique_config):
  return {
          'jar-publish': {
            'publish_extras': {
              'extra_test_jar_example': unique_config,
              },
            },
          'backends': {
            'packages': [
              'example.pants_publish_plugin',
              'internal_backend.repositories',
              ],
            },
          }


class JarPublishIntegrationTest(PantsRunIntegrationTest):
  SCALADOC = is_exe('scaladoc')
  JAVADOC = is_exe('javadoc')

  # This is where all pushdb properties files will end up.
  @property
  def pushdb_root(self):
    return os.path.join(get_buildroot(), 'testprojects', 'ivy', 'pushdb')

  def setUp(self):
    safe_rmtree(self.pushdb_root)

  def tearDown(self):
    safe_rmtree(self.pushdb_root)

  @pytest.mark.skipif('not JarPublishIntegrationTest.SCALADOC',
                      reason='No scaladoc binary on the PATH.')
  def test_scala_publish(self):
    unique_artifacts = {'com/pants/testproject/publish/jvm-example-lib/0.0.1-SNAPSHOT':
                        ['ivy-0.0.1-SNAPSHOT.xml',
                         'jvm-example-lib-0.0.1-SNAPSHOT.jar',
                         'jvm-example-lib-0.0.1-SNAPSHOT.pom',
                         'jvm-example-lib-0.0.1-SNAPSHOT-sources.jar'],
                        'com/pants/testproject/publish/hello/welcome/0.0.1-SNAPSHOT':
                        ['ivy-0.0.1-SNAPSHOT.xml',
                         'welcome-0.0.1-SNAPSHOT.jar',
                         'welcome-0.0.1-SNAPSHOT.pom',
                         'welcome-0.0.1-SNAPSHOT-sources.jar'],}
    self.publish_test('testprojects/src/scala/com/pants/testproject/publish:jvm-run-example-lib',
                      dict(unique_artifacts.items() + shared_artifacts('0.0.1-SNAPSHOT').items()),
                      ['com.pants.testproject.publish/hello-greet/publish.properties',
                       'com.pants.testproject.publish/jvm-example-lib/publish.properties',
                       'com.pants.testproject.publish.hello/welcome/publish.properties'],
                      extra_options=['--doc-scaladoc-skip'],
                      expected_primary_artifact_count=3)

  @pytest.mark.skipif('not JarPublishIntegrationTest.JAVADOC',
                      reason='No javadoc binary on the PATH.')
  def test_java_publish(self):
    self.publish_test('testprojects/src/java/com/pants/testproject/publish/hello/greet',
                      shared_artifacts('0.0.1-SNAPSHOT'),
                      ['com.pants.testproject.publish/hello-greet/publish.properties'],)

  def test_named_snapshot(self):
    name = "abcdef0123456789"
    self.publish_test('testprojects/src/java/com/pants/testproject/publish/hello/greet',
                      shared_artifacts(name),
                      ['com.pants.testproject.publish/hello-greet/publish.properties'],
                      extra_options=['--publish-named-snapshot=%s' % name])

  # Collect all the common factors for running a publish_extras test, and execute the test.
  def publish_extras_runner(self, extra_config=None, artifact_name=None, success_expected=True):
    self.publish_test('testprojects/src/java/com/pants/testproject/publish/hello/greet',
                      shared_artifacts('0.0.1-SNAPSHOT', artifact_name),
                      ['com.pants.testproject.publish/hello-greet/publish.properties'],
                      extra_options=['--doc-javadoc-skip'],
                      extra_config=extra_config,
                      extra_env={'WRAPPER_SRCPATH': 'examples/src/python'},
                      success_expected=success_expected)

  #
  # Run through all the permutations of the config parameters for publish_extras.
  #
  def test_publish_extras_name_classifier(self):
    self.publish_extras_runner(extra_config=publish_extra_config({
                                'override_name': '{target_provides_name}-extra_example',
                                'classifier': 'classy',
                                }),
                               artifact_name='hello-greet-extra_example-0.0.1-SNAPSHOT-classy.jar')

  def test_publish_extras_name(self):
    self.publish_extras_runner(extra_config=publish_extra_config({
                                'override_name': '{target_provides_name}-extra_example',
                                }),
                               artifact_name='hello-greet-extra_example-0.0.1-SNAPSHOT.jar')

  def test_publish_extras_name_extension(self):
    self.publish_extras_runner(extra_config=publish_extra_config({
                                'override_name': '{target_provides_name}-extra_example',
                                'extension': 'zip'
                                }),
                               artifact_name='hello-greet-extra_example-0.0.1-SNAPSHOT.zip')

  def test_publish_extras_extension(self):
    self.publish_extras_runner(extra_config=publish_extra_config({
                                'extension': 'zip'
                                }),
                               artifact_name='hello-greet-0.0.1-SNAPSHOT.zip')

  def test_publish_extras_extension_classifier(self):
    self.publish_extras_runner(extra_config=publish_extra_config({
                                'classifier': 'classy',
                                'extension': 'zip'
                                }),
                               artifact_name='hello-greet-0.0.1-SNAPSHOT-classy.zip')

  def test_publish_extras_classifier(self):
    self.publish_extras_runner(extra_config=publish_extra_config({
                                'classifier': 'classy',
                                }),
                               artifact_name='hello-greet-0.0.1-SNAPSHOT-classy.jar')

  # This test doesn't specify a proper set of parameters that uniquely name the extra artifact, and
  # should fail with an error from pants.
  def test_publish_extras_invalid_args(self):
    self.publish_extras_runner(extra_config=publish_extra_config({
                                'extension': 'jar',
                                }),
                               artifact_name='hello-greet-0.0.1-SNAPSHOT.jar',
                               success_expected=False)


  def publish_test(self, target, artifacts, pushdb_files, extra_options=None, extra_config=None,
                   extra_env=None, expected_primary_artifact_count=1, success_expected=True):
    """Tests that publishing the given target results in the expected output.

    :param target: Target to test.
    :param artifacts: A map from directories to a list of expected filenames.
    :param extra_options: Extra command-line options to the pants run.
    :param extra_config: Extra pants.ini configuration for the pants run.
    :param expected_primary_artifact_count: Number of artifacts we expect to be published.
    :param extra_env: Extra environment variables for the pants run."""

    with temporary_dir() as publish_dir:
      options = ['--publish-local=%s' % publish_dir,
                 '--no-publish-dryrun',
                 '--publish-force']
      if extra_options:
        options.extend(extra_options)

      yes = 'y' * expected_primary_artifact_count
      pants_run = self.run_pants(['publish', target] + options, config=extra_config,
                                 stdin_data=yes, extra_env=extra_env)

      if success_expected:
        self.assert_success(pants_run, "'pants goal publish' expected success, but failed instead.")
      else:
        self.assert_failure(pants_run, "'pants goal publish' expected failure, but succeeded instead.")
        return

      # New pushdb directory should be created for all artifacts.
      for pushdb_file in pushdb_files:
        self.assertTrue(os.path.exists(os.path.dirname(os.path.join(self.pushdb_root, pushdb_file))))

      # But because we are doing local publishes, no pushdb files are created
      for pushdb_file in pushdb_files:
        self.assertFalse(os.path.exists(os.path.join(self.pushdb_root, pushdb_file)))

      for directory, artifact_list in artifacts.items():
        for artifact in artifact_list:
          artifact_path = os.path.join(publish_dir, directory, artifact)
          self.assertTrue(os.path.exists(artifact_path))
