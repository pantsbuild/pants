# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.contextutil import temporary_dir, temporary_file_path
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class DepUsageIntegrationTest(PantsRunIntegrationTest):
  def test_dep_usage(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      with temporary_file_path(root_dir=self.workdir_root()) as path:
        dep_usage_args = [
          "dep-usage",
          "--dep-usage-jvm-size-estimator=linecount",
          "--dep-usage-jvm-output-file={}".format(path),
          "examples/src/java/org/pantsbuild/example/java_sources",
        ]
        pants_run = self.run_pants_with_workdir(dep_usage_args, workdir)
        self.assert_success(pants_run)
