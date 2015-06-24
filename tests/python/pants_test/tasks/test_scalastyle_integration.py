# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScalastyleIntegrationTest(PantsRunIntegrationTest):
  def test_scalastyle_cached(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      with temporary_dir(root_dir=self.workdir_root()) as cache:
        scalastyle_args = [
          'clean-all',
          'compile.scalastyle',
          "--cache-write-to=['{}']".format(cache),
          "--cache-read-from=['{}']".format(cache),
          'examples/src/scala/org/pantsbuild/example/hello/welcome'
        ]

        pants_run = self.run_pants_with_workdir(scalastyle_args, workdir)
        self.assert_success(pants_run)
        self.assertIn('Caching artifacts for 1 target.', pants_run.stdout_data)

        pants_run = self.run_pants_with_workdir(scalastyle_args, workdir)
        self.assert_success(pants_run)
        self.assertIn('Using cached artifacts for 1 target.', pants_run.stdout_data)
