# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.projects.base_project_integration_test import ProjectIntegrationTest


class TestProjectsIntegrationTest(ProjectIntegrationTest):

  def tests_testprojects(self):
    # TODO(Eric Ayers) find a better way to deal with tests that are known to fail.
    # right now, just split them into two categories and ignore them.

    # Targets that fail but shouldn't
    known_failing_targets = [
      # The following two targets lose out due to a resource collision, because `example_b` happens
      # to be first in the context, and test.junit mixes all classpaths.
      'testprojects/maven_layout/resource_collision/example_b/src/test/java/org/pantsbuild/duplicateres/exampleb:exampleb',
      'testprojects/maven_layout/resource_collision/example_c/src/test/java/org/pantsbuild/duplicateres/examplec:examplec',
    ]

    # Targets that are intended to fail
    negative_test_targets = [
      'testprojects/src/antlr/pants/backend/python/test:antlr_failure',
      'testprojects/src/java/org/pantsbuild/testproject/bundle:missing-files',
      'testprojects/src/java/org/pantsbuild/testproject/cycle1',
      'testprojects/src/java/org/pantsbuild/testproject/cycle2',
      'testprojects/src/java/org/pantsbuild/testproject/missingdepswhitelist.*',
      'testprojects/src/python/antlr:test_antlr_failure',
      'testprojects/src/scala/org/pantsbuild/testproject/compilation_failure',
      'testprojects/src/thrift/org/pantsbuild/thrift_linter:',
      'testprojects/tests/java/org/pantsbuild/testproject/empty:',
      'testprojects/tests/java/org/pantsbuild/testproject/dummies:failing_target',
      'testprojects/tests/python/pants/dummies:failing_target',
    ]

    targets_to_exclude = known_failing_targets + negative_test_targets
    exclude_opts = map(lambda target: '--exclude-target-regexp={}'.format(target), targets_to_exclude)
    pants_run = self.pants_test(['testprojects::'] + exclude_opts)
    self.assert_success(pants_run)
