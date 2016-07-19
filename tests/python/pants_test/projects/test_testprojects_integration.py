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
      # This will fail until we release and upgrade to junit runner 0.0.11.
      'testprojects/tests/java/org/pantsbuild/testproject/cucumber',
      # TODO: This one has a missing dependency, but is intended to succeed... should it?
      'testprojects/src/java/org/pantsbuild/testproject/thriftdeptest',
      # TODO(Eric Ayers): I don't understand why this fails
      'testprojects/src/java/org/pantsbuild/testproject/jvmprepcommand:compile-prep-command',
    ]

    # Targets that are intended to fail
    negative_test_targets = [
      'testprojects/maven_layout/provided_patching/leaf:fail',
      'testprojects/src/antlr/pants/backend/python/test:antlr_failure',
      'testprojects/src/java/org/pantsbuild/testproject/bundle:missing-files',
      'testprojects/src/java/org/pantsbuild/testproject/compilation_warnings:fatal',
      'testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target',
      'testprojects/src/java/org/pantsbuild/testproject/junit/earlyexit:tests',
      'testprojects/src/java/org/pantsbuild/testproject/junit/failing/tests/org/pantsbuild/tmp/tests',
      'testprojects/src/java/org/pantsbuild/testproject/junit/mixed/tests/org/pantsbuild/tmp/tests',
      'testprojects/src/java/org/pantsbuild/testproject/missingdepswhitelist.*',
      'testprojects/src/java/org/pantsbuild/testproject/missingdirectdepswhitelist:missingdirectdepswhitelist',
      'testprojects/src/java/org/pantsbuild/testproject/missingjardepswhitelist:missingjardepswhitelist',
      'testprojects/src/python/antlr:test_antlr_failure',
      'testprojects/src/scala/org/pantsbuild/testproject/compilation_failure',
      'testprojects/src/scala/org/pantsbuild/testproject/compilation_warnings:fatal',
      'testprojects/src/thrift/org/pantsbuild/thrift_linter:',
      'testprojects/src/java/org/pantsbuild/testproject/provided:c',
      'testprojects/tests/java/org/pantsbuild/testproject/dummies:failing_target',
      'testprojects/tests/java/org/pantsbuild/testproject/empty:',
      'testprojects/tests/python/pants/dummies:failing_target',
      # These don't pass without special config.
      'testprojects/tests/java/org/pantsbuild/testproject/depman:new-tests',
      'testprojects/tests/java/org/pantsbuild/testproject/depman:old-tests',
      'testprojects/tests/java/org/pantsbuild/testproject/htmlreport:htmlreport',
      'testprojects/tests/java/org/pantsbuild/testproject/parallel.*',
    ]

    # May not succeed without java8 installed
    need_java_8 = [
      'testprojects/src/java/org/pantsbuild/testproject/targetlevels/java8',
      'testprojects/tests/java/org/pantsbuild/testproject/testjvms',
      'testprojects/tests/java/org/pantsbuild/testproject/testjvms:eight',
      'testprojects/tests/java/org/pantsbuild/testproject/testjvms:eight-test-platform',
    ]

    # Targets for testing timeouts. These should only be run during specific integration tests,
    # because they take a long time to run.
    timeout_targets = [
      'testprojects/tests/python/pants/timeout:sleeping_target',
      'testprojects/tests/java/org/pantsbuild/testproject/timeout:sleeping_target',
       # Called with test_pytest_run_integration
      'testprojects/tests/python/pants/timeout:exceeds_timeout',
      'testprojects/tests/python/pants/timeout:ignores_terminate',
    ]

    deliberately_conflicting_targets = [
      'testprojects/src/python/interpreter_selection.*'
    ]

    targets_to_exclude = (known_failing_targets + negative_test_targets + need_java_8 +
                          timeout_targets + deliberately_conflicting_targets)
    exclude_opts = map(lambda target: '--exclude-target-regexp={}'.format(target),
                       targets_to_exclude)
    pants_run = self.pants_test(['testprojects::'] + exclude_opts)
    self.assert_success(pants_run)
