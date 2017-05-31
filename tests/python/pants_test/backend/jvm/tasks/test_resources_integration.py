# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ResourcesIntegrationTest(PantsRunIntegrationTest):

  def test_resources_all(self):
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
        'resources',
        'testprojects/src/resources/org/pantsbuild/testproject/fileresources:lib'],
        workdir)
      self.assert_success(pants_run)
      out_dir = os.path.join(workdir, 'resources', 'prepare',
                             'current', 'testprojects.src.resources.org.pantsbuild.testproject.fileresources.all-files',
                             'current', 'org', 'pantsbuild', 'testproject', 'fileresources')
      self.assertFalse(os.path.exists(os.path.join(out_dir, 'BUILD')))
      self.assertTrue(os.path.exists(os.path.join(out_dir, 'src', 'File.java')))
      self.assertTrue(os.path.exists(os.path.join(out_dir, 'src', 'File.txt')))
      self.assertTrue(os.path.exists(os.path.join(out_dir, 'src', 'subdirectory', 'subdirectory.txt')))
      # Hidden files are excluded from Globs by default in 1.3+
      self.assertFalse(os.path.exists(os.path.join(out_dir, '.hidden', 'Hidden.java')))
