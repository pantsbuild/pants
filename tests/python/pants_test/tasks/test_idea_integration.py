# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class IdeaIntegrationTest(PantsRunIntegrationTest):

  def _idea_test(self, specs, project_dir=None):
    """Helper method that tests idea generation on the input spec list."""
    if project_dir is None:
      project_dir = os.path.join('.pants.d', 'tmp', 'test-idea')

    if not os.path.exists(project_dir):
      os.makedirs(project_dir)
    with temporary_dir(root_dir=project_dir) as path:
      pants_run = self.run_pants(['goal', 'idea',] + specs
          + ['--idea-project-dir={dir}'.format(dir=path), '--no-idea-open',])
      self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                        "goal idea expected success, got {0}\n"
                        "got stderr:\n{1}\n"
                        "got stdout:\n{2}\n".format(pants_run.returncode,
                                                    pants_run.stderr_data,
                                                    pants_run.stdout_data))
      # TODO(Garrett Malmquist): Actually validate the contents of the project files, rather than just
      # checking if they exist.
      expected_files = ('project.iml', 'project.ipr',)
      self.assertTrue(os.path.exists(path),
          'Failed to find project_dir at {dir}.'.format(dir=path))
      self.assertTrue(all(os.path.exists(os.path.join(path, name))
          for name in expected_files))

  # Testing IDEA integration on lots of different targets which require different functionalities to
  # make sure that everything that needs to happen for idea gen does happen.

  def test_idea_on_alternate_project_dir(self):
    alt_dir = os.path.join('.pants.d', 'tmp', 'some', 'random', 'directory', 'for', 'idea', 'stuff')
    self._idea_test(['src/java/com/pants/examples/testproject/hello::'], project_dir=alt_dir)

  def test_idea_on_protobuf(self):
    self._idea_test(['src/java/com/pants/examples/protobuf::'])

  def test_idea_on_jaxb(self): # Make sure it works without ::, pulling deps as necessary.
    self._idea_test(['src/java/com/pants/examples/jaxb/main'])

  def test_idea_on_unicode(self):
    self._idea_test(['src/java/com/pants/testproject/unicode::'])

  def test_idea_on_hello(self):
    self._idea_test(['src/java/com/pants/examples/hello::'])

  def test_idea_on_annotations(self):
    self._idea_test(['src/java/com/pants/examples/annotation::'])

  def test_idea_on_all_examples(self):
    self._idea_test(['src/java/com/pants/examples::'])