# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CheckstyleIntegrationTest(PantsRunIntegrationTest):
  def test_checkstyle_cached(self):
    with temporary_dir(root_dir=self.workdir_root()) as tmp_workdir:
      with temporary_dir(root_dir=self.workdir_root()) as artifact_cache:
        checkstyle_args = [
          'clean-all',
          'compile.checkstyle',
          "--write-artifact-caches=['{}']".format(artifact_cache),
          "--read-artifact-caches=['{}']".format(artifact_cache),
          'testprojects/src/java/org/pantsbuild/testproject/java_style::'
        ]

        pants_run = self.run_pants_with_workdir(checkstyle_args, tmp_workdir)
        self.assert_success(pants_run)
        self.assertIn('Caching artifacts for 1 target.', pants_run.stdout_data)

        pants_run = self.run_pants_with_workdir(checkstyle_args, tmp_workdir)
        self.assert_success(pants_run)
        self.assertIn('Using cached artifacts for 1 target.', pants_run.stdout_data)
