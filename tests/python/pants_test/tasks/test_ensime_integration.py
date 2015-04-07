# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class EnsimeIntegrationTest(PantsRunIntegrationTest):

  def _ensime_test(self, specs, project_dir=os.path.join('.pants.d', 'tmp-ensime', 'project'),
                   project_name='project'):
    """Helper method that tests ensime generation on the input spec list."""

    if not os.path.exists(project_dir):
      os.makedirs(project_dir)
    with temporary_dir(root_dir=project_dir) as path:
      pants_run = self.run_pants(['ensime', '--project-dir={dir}'.format(dir=path)] + specs)
      self.assert_success(pants_run)
      # TODO: Actually validate the contents of the project files, rather than just
      # checking if they exist.
      expected_files = ('.ensime',)
      workdir = os.path.join(path, project_name)
      self.assertTrue(os.path.exists(workdir),
          'Failed to find project_dir at {dir}.'.format(dir=workdir))
      self.assertTrue(all(os.path.exists(os.path.join(workdir, name)) for name in expected_files),
                      'Failed to find one of the ensime project files at {dir}'.format(dir=path))

  # Testing Ensime integration on a sample project
  def test_ensime_on_all_examples(self):
    self._ensime_test(['examples/src/scala/org/pantsbuild/example::'])
