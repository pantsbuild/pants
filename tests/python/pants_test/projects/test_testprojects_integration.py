# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import math

from pants.util.memo import memoized_property
from pants_test.pants_run_integration_test import ensure_engine
from pants_test.projects.base_project_integration_test import ProjectIntegrationTest


class TestProjectsIntegrationTest(ProjectIntegrationTest):
  # To avoid having a single test method which covers all of `testprojects` (which
  # would run for a very long time with no output, and be more difficult to iterate
  # on), we shard all of the targets under `testprojects` into _SHARDS test methods.
  #
  # NB: Do not change this value without matching the number of test methods.
  _SHARDS = 16

  @memoized_property
  def targets(self):
    """A sequence of target name strings."""

    # Targets that fail but shouldn't
    known_failing_targets = [
      # The following two targets lose out due to a resource collision, because `example_b` happens
      # to be first in the context, and test.junit mixes all classpaths.
      'testprojects/maven_layout/resource_collision/example_b/src/test/java/org/pantsbuild/duplicateres/exampleb:exampleb',
      'testprojects/maven_layout/resource_collision/example_c/src/test/java/org/pantsbuild/duplicateres/examplec:examplec',
      # TODO: This one has a missing dependency, but is intended to succeed... should it?
      'testprojects/src/java/org/pantsbuild/testproject/thriftdeptest',
      # TODO(Eric Ayers): I don't understand why this fails
      'testprojects/src/java/org/pantsbuild/testproject/jvmprepcommand:compile-prep-command',
    ]

    # Targets that are intended to fail
    negative_test_targets = [
      'testprojects/maven_layout/provided_patching/leaf:fail',
      'testprojects/src/antlr/python/test:antlr_failure',
      'testprojects/src/java/org/pantsbuild/testproject/bundle:missing-files',
      'testprojects/src/java/org/pantsbuild/testproject/compilation_warnings:fatal',
      'testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target',
      'testprojects/src/java/org/pantsbuild/testproject/junit/earlyexit:tests',
      'testprojects/src/java/org/pantsbuild/testproject/junit/failing/tests/org/pantsbuild/tmp/tests',
      'testprojects/src/java/org/pantsbuild/testproject/junit/mixed/tests/org/pantsbuild/tmp/tests',
      'testprojects/src/java/org/pantsbuild/testproject/missingdepswhitelist.*',
      'testprojects/src/java/org/pantsbuild/testproject/missingdirectdepswhitelist:missingdirectdepswhitelist',
      'testprojects/src/java/org/pantsbuild/testproject/missingjardepswhitelist:missingjardepswhitelist',
      'testprojects/src/scala/org/pantsbuild/testproject/compilation_failure',
      'testprojects/src/scala/org/pantsbuild/testproject/compilation_warnings:fatal',
      'testprojects/src/thrift/org/pantsbuild/thrift_exports:C-without-exports',
      'testprojects/src/thrift/org/pantsbuild/thrift_linter:',
      'testprojects/src/java/org/pantsbuild/testproject/provided:c',
      'testprojects/tests/java/org/pantsbuild/testproject/dummies:failing_target',
      'testprojects/tests/java/org/pantsbuild/testproject/empty:',
      'testprojects/tests/java/org/pantsbuild/testproject/fail256:fail256',
      'testprojects/tests/python/pants/dummies:failing_target',
      'testprojects/tests/scala/org/pantsbuild/testproject/non_exports:C',
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
      'examples/src/java/org/pantsbuild/example/plugin',
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

    # Run list with exclude options, then parse and sort output.
    pants_run = self.run_pants(['list', 'testprojects::', 'examples::'] + exclude_opts)
    self.assert_success(pants_run)
    return sorted(pants_run.stdout_data.split())

  def targets_for_shard(self, shard):
    if shard < 0 or shard >= self._SHARDS:
      raise Exception('Invalid shard: {} / {}'.format(shard, self._SHARDS))

    per_shard = int(math.ceil(len(self.targets) / self._SHARDS))
    offset = (per_shard*shard)
    return self.targets[offset:offset + per_shard]

  @ensure_engine
  def run_shard(self, shard):
    targets = self.targets_for_shard(shard)
    pants_run = self.pants_test(targets + ['--jvm-platform-default-platform=java7',
                                           '--gen-protoc-import-from-root'])
    self.assert_success(pants_run)

  def test_self(self):
    self.assertEquals([t for s in range(0, self._SHARDS)
                         for t in self.targets_for_shard(s)], 
                      self.targets)

  def test_shard_0(self):
    self.run_shard(0)

  def test_shard_1(self):
    self.run_shard(1)

  def test_shard_2(self):
    self.run_shard(2)

  def test_shard_3(self):
    self.run_shard(3)

  def test_shard_4(self):
    self.run_shard(4)

  def test_shard_5(self):
    self.run_shard(5)

  def test_shard_6(self):
    self.run_shard(6)

  def test_shard_7(self):
    self.run_shard(7)

  def test_shard_8(self):
    self.run_shard(8)

  def test_shard_9(self):
    self.run_shard(9)

  def test_shard_10(self):
    self.run_shard(10)

  def test_shard_11(self):
    self.run_shard(11)

  def test_shard_12(self):
    self.run_shard(12)

  def test_shard_13(self):
    self.run_shard(13)

  def test_shard_14(self):
    self.run_shard(14)

  def test_shard_15(self):
    self.run_shard(15)
