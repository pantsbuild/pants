# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScalastyleIntegrationTest(PantsRunIntegrationTest):

  def test_scalastyle_without_quiet(self):
    scalastyle_args = [
      'lint.scalastyle',
      '--config=examples/src/scala/org/pantsbuild/example/styleissue/style.xml',
      'examples/src/scala/org/pantsbuild/example/styleissue',
      ]
    pants_run = self.run_pants(scalastyle_args)
    self.assertIn('Found 2 errors', pants_run.stdout_data)

  def test_scalastyle_with_quiet(self):
    scalastyle_args = [
      'lint.scalastyle',
      '--config=examples/src/scala/org/pantsbuild/example/styleissue/style.xml',
      '--quiet',
      'examples/src/scala/org/pantsbuild/example/styleissue',
      ]
    pants_run = self.run_pants(scalastyle_args)
    self.assertNotIn('Found 2 errors', pants_run.stdout_data)
