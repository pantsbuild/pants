# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.projects.base_project_integration_test import ProjectIntegrationTest


class ExamplesIntegrationTest(ProjectIntegrationTest):
  def tests_examples(self):
    # TODO: Remove the --exclude-target-regexp once we're on Java 8 everywhere.
    pants_run = self.pants_test(['examples::',
                                 '--exclude-target-regexp=examples/src/java/org/pantsbuild/example/plugin'])
    self.assert_success(pants_run)
