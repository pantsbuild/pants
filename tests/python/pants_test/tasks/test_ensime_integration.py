# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class EnsimeIntegrationTest(PantsRunIntegrationTest):

  def _ensime_test(self, specs, project_dir = os.path.join('.pants.d', 'tmp-ensime', 'project'),
      project_name='project'):
    """Helper method that tests ensime generation on the input spec list."""

    if not os.path.exists(project_dir):
      os.makedirs(project_dir)
    with temporary_dir(root_dir=project_dir) as path:
      pants_run = self.run_pants(['goal', 'ensime',] + specs
            + ['--ensime-project-dir={dir}'.format(dir=path), ])

      self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                        "goal ensime expected success, got {0}\n"
                        "got stderr:\n{1}\n"
                        "got stdout:\n{2}\n".format(pants_run.returncode,
                                                    pants_run.stderr_data,
                                                    pants_run.stdout_data))
      # TODO: Actually validate the contents of the project files, rather than just
      # checking if they exist.
      expected_files = ('.ensime',)
      workdir = os.path.join(path, project_name)
      self.assertTrue(os.path.exists(workdir),
          'Failed to find project_dir at {dir}.'.format(dir=workdir))
      self.assertTrue(all(os.path.exists(os.path.join(workdir, name))
          for name in expected_files), 'Failed to find one of the ensime project files at {dir}'.format(dir=path))

  # Testing Ensime integration on a sample project
  def test_ensime_on_all_examples(self):
    self._ensime_test(['examples/src/scala/com/pants/example::'])
