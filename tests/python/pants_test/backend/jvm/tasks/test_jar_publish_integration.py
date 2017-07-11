# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_rmtree
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


def shared_artifacts(version, extra_jar=None):
  published_file_list = ['ivy-{0}.xml'.format(version),
                         'hello-greet-{0}.jar'.format(version),
                         'hello-greet-{0}.pom'.format(version),
                         'hello-greet-{0}-sources.jar'.format(version)]
  if extra_jar:
    published_file_list.append(extra_jar)
  return {'org/pantsbuild/testproject/publish/hello-greet/{0}'.format(version): published_file_list}


# TODO: Right now some options are set via config and some via cmd-line flags. Normalize this?
def publish_extra_config(unique_config):
  return {
    'GLOBAL': {
      # Turn off --verify-config as some scopes in pants.ini will not be
      # recognized due to the select few backend packages.
      'verify_config': False,
      'pythonpath': [
        'examples/src/python',
        'pants-plugins/src/python',
      ],
      'backend_packages': [
        'example.pants_publish_plugin',
        'internal_backend.repositories',
        'pants.backend.codegen',
        'pants.backend.jvm',
      ],
    },
    'publish.jar': {
      'publish_extras': {
        'extra_test_jar_example': unique_config,
      },
    },
  }


class JarPublishIntegrationTest(PantsRunIntegrationTest):
  GOLDEN_DATA_DIR = 'tests/python/pants_test/tasks/jar_publish_resources/'

  # This is where all pushdb properties files will end up.
  @property
  def pushdb_root(self):
    return os.path.join(get_buildroot(), 'testprojects', 'ivy', 'pushdb')

  def setUp(self):
    # This attribute is required to see the full diff between ivy and pom files.
    self.maxDiff = None
    safe_rmtree(self.pushdb_root)

  def tearDown(self):
    safe_rmtree(self.pushdb_root)

  def test_scala_publish(self):
    unique_artifacts = {'org/pantsbuild/testproject/publish/jvm-example-lib_2.11/0.0.1-SNAPSHOT':
                        ['ivy-0.0.1-SNAPSHOT.xml',
                         'jvm-example-lib_2.11-0.0.1-SNAPSHOT.jar',
                         'jvm-example-lib_2.11-0.0.1-SNAPSHOT.pom',
                         'jvm-example-lib_2.11-0.0.1-SNAPSHOT-sources.jar'],
                        'org/pantsbuild/testproject/publish/hello/welcome_2.11/0.0.1-SNAPSHOT':
                        ['ivy-0.0.1-SNAPSHOT.xml',
                         'welcome_2.11-0.0.1-SNAPSHOT.jar',
                         'welcome_2.11-0.0.1-SNAPSHOT.pom',
                         'welcome_2.11-0.0.1-SNAPSHOT-sources.jar']}
    self.publish_test('testprojects/src/scala/org/pantsbuild/testproject/publish'
                      ':jvm-run-example-lib',
                      dict(unique_artifacts.items() + shared_artifacts('0.0.1-SNAPSHOT').items()),
                      ['org.pantsbuild.testproject.publish/hello-greet/publish.properties',
                       'org.pantsbuild.testproject.publish/jvm-example-lib_2.11/publish.properties',
                       'org.pantsbuild.testproject.publish.hello/welcome_2.11/publish.properties'],
                      extra_options=['--doc-scaladoc-skip'],
                      expected_primary_artifact_count=3,
                      assert_publish_config_contents=True)

  def test_java_publish(self):
    self.publish_test('testprojects/src/java/org/pantsbuild/testproject/publish/hello/greet',
                      shared_artifacts('0.0.1-SNAPSHOT'),
                      ['org.pantsbuild.testproject.publish/hello-greet/publish.properties'],)

  def test_protobuf_publish(self):
    unique_artifacts = {'org/pantsbuild/testproject/publish/protobuf/protobuf-java/0.0.1-SNAPSHOT':
                        ['ivy-0.0.1-SNAPSHOT.xml',
                         'protobuf-java-0.0.1-SNAPSHOT.jar',
                         'protobuf-java-0.0.1-SNAPSHOT.pom',
                         'protobuf-java-0.0.1-SNAPSHOT-sources.jar'],
                        'org/pantsbuild/testproject/protobuf/distance/0.0.1-SNAPSHOT/':
                        ['ivy-0.0.1-SNAPSHOT.xml',
                         'distance-0.0.1-SNAPSHOT.jar',
                         'distance-0.0.1-SNAPSHOT.pom',
                         'distance-0.0.1-SNAPSHOT-sources.jar']}
    self.publish_test('testprojects/src/java/org/pantsbuild/testproject/publish/protobuf'
                      ':protobuf-java',
                      unique_artifacts,
                      ['org.pantsbuild.testproject.publish.protobuf/protobuf-java/'
                       'publish.properties',
                       'org.pantsbuild.testproject.protobuf/distance/publish.properties'],
                      extra_options=['--doc-javadoc-skip'],
                      expected_primary_artifact_count=2)

  def test_named_snapshot(self):
    name = "abcdef0123456789"
    self.publish_test('testprojects/src/java/org/pantsbuild/testproject/publish/hello/greet',
                      shared_artifacts(name),
                      ['org.pantsbuild.testproject.publish/hello-greet/publish.properties'],
                      extra_options=['--named-snapshot={}'.format(name)])

  def test_publish_override_flag_succeeds(self):
    override = "com.twitter.foo#baz=0.1.0"
    self.publish_test('testprojects/src/java/org/pantsbuild/testproject/publish/hello/greet',
                      shared_artifacts('0.0.1-SNAPSHOT'),
                      ['org.pantsbuild.testproject.publish/hello-greet/publish.properties'],
                      extra_options=['--override={}'.format(override)])

  # Collect all the common factors for running a publish_extras test, and execute the test.
  def publish_extras_runner(self, extra_config=None, artifact_name=None, success_expected=True):
    self.publish_test('testprojects/src/java/org/pantsbuild/testproject/publish/hello/greet',
                      shared_artifacts('0.0.1-SNAPSHOT', artifact_name),
                      ['org.pantsbuild.testproject.publish/hello-greet/publish.properties'],
                      extra_options=['--doc-javadoc-skip'],
                      extra_config=extra_config,
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

  def test_scala_publish_classifiers(self):
    self.publish_test('testprojects/src/scala/org/pantsbuild/testproject/publish/classifiers',
                      dict({
                        'org/pantsbuild/testproject/publish/classifiers_2.11/0.0.1-SNAPSHOT': [
                          'classifiers_2.11-0.0.1-SNAPSHOT.pom',
                          'ivy-0.0.1-SNAPSHOT.xml',
                        ]}),
                      [],
                      assert_publish_config_contents=True)

  def test_override_via_coord(self):
    self.publish_test(
      target='testprojects/src/scala/org/pantsbuild/testproject/publish/classifiers',
      artifacts=dict({'org/pantsbuild/testproject/publish/classifiers_2.11/1.2.3-SNAPSHOT': [
                        'classifiers_2.11-1.2.3-SNAPSHOT.pom',
                        'ivy-1.2.3-SNAPSHOT.xml',
                      ]}),
      pushdb_files=[],
      extra_options=['--override=org.pantsbuild.testproject.publish#classifiers_2.11=1.2.3'],
      assert_publish_config_contents=True)

  def test_override_via_address(self):
    target = 'testprojects/src/scala/org/pantsbuild/testproject/publish/classifiers'
    self.publish_test(
      target=target,
      artifacts=dict({'org/pantsbuild/testproject/publish/classifiers_2.11/1.2.3-SNAPSHOT': [
        'classifiers_2.11-1.2.3-SNAPSHOT.pom',
        'ivy-1.2.3-SNAPSHOT.xml',
      ]}),
      pushdb_files=[],
      extra_options=['--override={}=1.2.3'.format(target)],
      assert_publish_config_contents=True)

  def publish_test(self, target, artifacts, pushdb_files, extra_options=None, extra_config=None,
                   extra_env=None, expected_primary_artifact_count=1, success_expected=True,
                   assert_publish_config_contents=False):
    """Tests that publishing the given target results in the expected output.

    :param target: Target to test.
    :param artifacts: A map from directories to a list of expected filenames.
    :param pushdb_files: list of pushdb files that would be created if this weren't a local publish
    :param extra_options: Extra command-line options to the pants run.
    :param extra_config: Extra pants.ini configuration for the pants run.
    :param expected_primary_artifact_count: Number of artifacts we expect to be published.
    :param extra_env: Extra environment variables for the pants run.
    :param assert_publish_config_contents: Test the contents of the generated ivy and pom file.
           If set to True, compares the generated ivy.xml and pom files in
           tests/python/pants_test/tasks/jar_publish_resources/<package_name>/<artifact_name>/
    """

    with temporary_dir() as publish_dir:
      options = ['--local={}'.format(publish_dir),
                 '--no-dryrun',
                 '--force']
      if extra_options:
        options.extend(extra_options)

      pants_run = self.run_pants(['publish.jar'] + options + [target], config=extra_config,
                                 extra_env=extra_env)
      if success_expected:
        self.assert_success(pants_run, "'pants goal publish' expected success, but failed instead.")
      else:
        self.assert_failure(pants_run,
                            "'pants goal publish' expected failure, but succeeded instead.")
        return

      # New pushdb directory should be created for all artifacts.
      for pushdb_file in pushdb_files:
        pushdb_dir = os.path.dirname(os.path.join(self.pushdb_root, pushdb_file))
        self.assertTrue(os.path.exists(pushdb_dir))

      # But because we are doing local publishes, no pushdb files are created
      for pushdb_file in pushdb_files:
        self.assertFalse(os.path.exists(os.path.join(self.pushdb_root, pushdb_file)))

      for directory, artifact_list in artifacts.items():
        for artifact in artifact_list:
          artifact_path = os.path.join(publish_dir, directory, artifact)
          self.assertTrue(os.path.exists(artifact_path))
          if assert_publish_config_contents:
            if artifact.endswith('xml') or artifact.endswith('pom'):
              self.compare_file_contents(artifact_path, directory)

  def compare_file_contents(self, artifact_path, directory):
    """
    Tests the ivy.xml and pom
    :param artifact_path: Path of the artifact
    :param directory: Directory where the artifact resides.
    :return:
    """
    # Strip away the version number
    [package_dir, artifact_name, version] = directory.rsplit(os.path.sep, 2)
    file_name = os.path.basename(artifact_path)
    golden_file_nm = os.path.join(JarPublishIntegrationTest.GOLDEN_DATA_DIR,
                                  package_dir.replace(os.path.sep, '.'), artifact_name, file_name)
    with open(artifact_path, 'r') as test_file:
      generated_file = test_file.read()
      with open(golden_file_nm, 'r') as golden_file:
        golden_file_contents = golden_file.read()
        # Remove the publication sha attribute from ivy.xml
        if artifact_path.endswith('.xml'):
          generated_file = re.sub(r'publication=.*', '/>', generated_file)
      return self.assertMultiLineEqual(generated_file, golden_file_contents)
