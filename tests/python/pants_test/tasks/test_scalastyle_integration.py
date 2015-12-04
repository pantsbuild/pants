# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pytest

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScalastyleIntegrationTest(PantsRunIntegrationTest):

  @pytest.mark.xfail
  # This test is now expected to fail due to changes in caching behaviour.
  # TODO(Tansy Arron): Write a general purpose incremental compile test.
  # https://github.com/pantsbuild/pants/issues/2591
  def test_scalastyle_cached(self):
    with self.temporary_cachedir() as cache:
      with self.temporary_workdir() as workdir:
        scalastyle_args = [
          'clean-all',
          'compile.scalastyle',
          "--cache-write-to=['{}']".format(cache),
          "--cache-read-from=['{}']".format(cache),
          'examples/tests/scala/org/pantsbuild/example/hello/welcome',
          '-ldebug'
        ]

        pants_run = self.run_pants_with_workdir(scalastyle_args, workdir)
        self.assert_success(pants_run)
        self.assertIn('abc_Scalastyle_compile_scalastyle will write to local artifact cache',
            pants_run.stdout_data)

        pants_run = self.run_pants_with_workdir(scalastyle_args, workdir)
        self.assert_success(pants_run)
        self.assertIn('abc_Scalastyle_compile_scalastyle will read from local artifact cache',
            pants_run.stdout_data)
        # make sure we are *only* reading from the cache and not also writing,
        # implying there was as a cache hit
        self.assertNotIn('abc_Scalastyle_compile_scalastyle will write to local artifact cache',
            pants_run.stdout_data)

  def test_scalastyle_without_quiet(self):
    scalastyle_args = [
      'compile.scalastyle',
      '--config=examples/src/scala/org/pantsbuild/example/styleissue/style.xml',
      'examples/src/scala/org/pantsbuild/example/styleissue',
      ]
    pants_run = self.run_pants(scalastyle_args)
    self.assertIn('Found 2 errors', pants_run.stdout_data)

  def test_scalastyle_with_quiet(self):
    scalastyle_args = [
      'compile.scalastyle',
      '--config=examples/src/scala/org/pantsbuild/example/styleissue/style.xml',
      '--quiet',
      'examples/src/scala/org/pantsbuild/example/styleissue',
      ]
    pants_run = self.run_pants(scalastyle_args)
    self.assertNotIn('Found 2 errors', pants_run.stdout_data)
