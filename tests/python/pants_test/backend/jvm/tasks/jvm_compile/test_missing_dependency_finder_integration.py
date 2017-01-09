# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class MissingDependencyFinderIntegrationTest(PantsRunIntegrationTest):

  def test_missing_deps_found(self):
    target = 'testprojects/src/java/org/pantsbuild/testproject/missingjardepswhitelist:missingjardepswhitelist'
    run = self.run_pants(['compile', target, '--compile-zinc-suggest-missing-deps'])
    self.assert_failure(run)
    self.assertTrue('Found the following deps from target\'s transitive dependencies '
                    'that contain the not found classes:\n  '
                    '  com.google.common.io.Closer: 3rdparty:guava', run.stdout_data)

  def test_missing_deps_not_found(self):
    target = 'testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target'
    run = self.run_pants(['compile', target, '--compile-zinc-suggest-missing-deps'])
    self.assert_failure(run)
    self.assertTrue('Unable to find any deps from target\'s transitive dependencies '
                    'that contain the following not found classes:\n'
                    '  System2.out', run.stdout_data)
