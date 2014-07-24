# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import pytest

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.tasks.test_base import is_exe

class JarPublishIntegrationTest(PantsRunIntegrationTest):
  SCALADOC = is_exe('scaladoc')
  JAVADOC = is_exe('javadoc')

  @pytest.mark.skipif('not JarPublishIntegrationTest.SCALADOC',
                      reason='No scaladoc binary on the PATH.')
  def test_scala_publish(self):
    self.publish_test('src/scala/com/pants/example:jvm-run-example-lib',
                      'com/pants/example/jvm-example-lib/0.0.1-SNAPSHOT',
                      ['ivy-0.0.1-SNAPSHOT.xml',
                       'jvm-example-lib-0.0.1-SNAPSHOT.jar',
                       'jvm-example-lib-0.0.1-SNAPSHOT.pom',
                       'jvm-example-lib-0.0.1-SNAPSHOT-sources.jar'],
                      extra_options=['--doc-scaladoc-skip'])

  @pytest.mark.skipif('not JarPublishIntegrationTest.JAVADOC',
                      reason='No javadoc binary on the PATH.')
  def test_java_publish(self):
    self.publish_test('src/java/com/pants/examples/hello/greet',
                      'com/pants/examples/hello-greet/0.0.1-SNAPSHOT/',
                      ['ivy-0.0.1-SNAPSHOT.xml',
                       'hello-greet-0.0.1-SNAPSHOT.jar',
                       'hello-greet-0.0.1-SNAPSHOT.pom',
                       'hello-greet-0.0.1-SNAPSHOT-javadoc.jar',
                       'hello-greet-0.0.1-SNAPSHOT-sources.jar'])

  def publish_test(self, target, package_namespace, artifacts, extra_options=None,
                   expected_primary_artifact_count=1):

    with temporary_dir() as publish_dir:
      options = ['--publish-local=%s' % publish_dir,
                 '--no-publish-dryrun',
                 '--publish-force']
      if extra_options:
        options.extend(extra_options)

      yes = 'y' * expected_primary_artifact_count
      pants_run = self.run_pants(['goal', 'publish', target] + options, stdin_data=yes)
      self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                        "goal publish expected success, got {0}\n"
                        "got stderr:\n{1}\n"
                        "got stdout:\n{2}\n".format(pants_run.returncode,
                                                    pants_run.stderr_data,
                                                    pants_run.stdout_data))
      for artifact in artifacts:
        artifact_path = os.path.join(publish_dir, package_namespace, artifact)
        self.assertTrue(os.path.exists(artifact_path))

