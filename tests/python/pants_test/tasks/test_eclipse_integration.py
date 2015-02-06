# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class EclipseIntegrationTest(PantsRunIntegrationTest):
  def _eclipse_test(self, specs, project_dir=os.path.join('.pants.d', 'tmp', 'test-eclipse'),
                    project_name='project'):
    """Helper method that tests eclipse generation on the input spec list."""

    if not os.path.exists(project_dir):
      os.makedirs(project_dir)
    with temporary_dir(root_dir=project_dir) as path:
      pants_run = self.run_pants(['eclipse', '--project-dir={dir}'.format(dir=path)] + specs)
      self.assert_success(pants_run)

      expected_files = ('.classpath', '.project',)
      workdir = os.path.join(path, project_name)
      self.assertTrue(os.path.exists(workdir),
          'Failed to find project_dir at {dir}.'.format(dir=workdir))
      self.assertTrue(all(os.path.exists(os.path.join(workdir, name))
          for name in expected_files))
      # return contents of .classpath so we can verify it
      with open(os.path.join(workdir, '.classpath')) as classpath_f:
        classpath = classpath_f.read()
      # should be at least one input; if not we may have the wrong target path
      self.assertIn('<classpathentry kind="src"', classpath)
      return classpath

  # Test Eclipse generation on example targets; ideally should test that the build "works"

  def test_eclipse_on_protobuf(self):
    self._eclipse_test(['examples/src/java/com/pants/examples/protobuf::'])

  def test_eclipse_on_jaxb(self):
    self._eclipse_test(['examples/src/java/com/pants/examples/jaxb/main'])

  def test_eclipse_on_unicode(self):
    self._eclipse_test(['testprojects/src/java/com/pants/testproject/unicode::'])

  def test_eclipse_on_hello(self):
    self._eclipse_test(['examples/src/java/com/pants/examples/hello::'])

  def test_eclipse_on_annotations(self):
    self._eclipse_test(['examples/src/java/com/pants/examples/annotation::'])

  def test_eclipse_on_all_examples(self):
    self._eclipse_test(['examples/src/java/com/pants/examples::'])

  def test_eclipse_on_java_sources(self):
    classpath = self._eclipse_test(['testprojects/src/scala/com/pants/testproject/javasources::'])
    self.assertIn('path="testprojects.src.java"', classpath)

  def test_eclipse_on_thriftdeptest(self):
    self._eclipse_test(['testprojects/src/java/com/pants/testproject/thriftdeptest::'])

  def test_eclipse_on_scaladepsonboth(self):
    classpath = self._eclipse_test(['testprojects/src/scala/com/pants/testproject/scaladepsonboth::'])
    # Previously Java dependencies didn't get included
    self.assertIn('path="testprojects.src.java"', classpath)
