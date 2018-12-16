# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import math
from builtins import range

from pants.util.memo import memoized_property
from pants_test.pants_run_integration_test import ensure_resolver
from pants_test.projects.base_project_integration_test import ProjectIntegrationTest


class TestProjectsIntegrationTest(ProjectIntegrationTest):
  # To avoid having a single test method which covers all of `testprojects` (which
  # would run for a very long time with no output, and be more difficult to iterate
  # on), we shard all of the targets under `testprojects` into _SHARDS test methods.
  #
  # NB: Do not change this value without matching the number of test methods.
  _SHARDS = 64

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
      'testprojects/src/java/org/pantsbuild/testproject/runtime:compile-fail',
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
      'testprojects/src/scala/org/pantsbuild/testproject/exclude_direct_dep',
      'testprojects/tests/python/pants/timeout:terminates_self',
      # These don't pass without special config.
      'testprojects/tests/java/org/pantsbuild/testproject/depman:new-tests',
      'testprojects/tests/java/org/pantsbuild/testproject/depman:old-tests',
      'testprojects/tests/java/org/pantsbuild/testproject/htmlreport:htmlreport',
      'testprojects/tests/java/org/pantsbuild/testproject/parallel.*',
      'testprojects/src/python/python_distribution/fasthello_with_install_requires.*',
      'testprojects/src/python/unicode/compilation_failure',
    ]

    # May not succeed without java8 installed
    need_java_8 = [
      'testprojects/src/java/org/pantsbuild/testproject/targetlevels/java8',
      'testprojects/tests/java/org/pantsbuild/testproject/testjvms',
      'testprojects/tests/java/org/pantsbuild/testproject/testjvms:eight',
      'testprojects/tests/java/org/pantsbuild/testproject/testjvms:eight-test-platform',
      'examples/src/java/org/pantsbuild/example/plugin',
    ]

    # Interpreter will not resolve correctly when Pants is constrained to Python 3
    python2_only = [
      # tested in test_antlr_py_gen_integration.py
      'testprojects/src/python/antlr'
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

    simply_skip = [
      # Already tested at pants_test.backend.jvm.targets.test_jar_dependency_integration.JarDependencyIntegrationTest
      'testprojects/3rdparty/org/pantsbuild/testprojects:testprojects',
      # Already tested in 'PantsRequirementIntegrationTest' and 'SetupPyIntegrationTest'.
      'testprojects/pants-plugins/*',
      'testprojects/src/python/python_distribution/ctypes:ctypes_test',
      'testprojects/src/python/python_distribution/ctypes_with_third_party:ctypes_test',
      'testprojects/src/python/python_distribution/ctypes_with_extra_compiler_flags:bin',
    ]

    targets_to_exclude = (known_failing_targets + negative_test_targets + need_java_8 + python2_only +
                          timeout_targets + deliberately_conflicting_targets + simply_skip)
    exclude_opts = ['--exclude-target-regexp={}'.format(target) for target in targets_to_exclude]

    # Run list with exclude options, then parse and sort output.
    pants_run = self.run_pants(['list', 'testprojects::', 'examples::'] + exclude_opts)
    self.assert_success(pants_run)
    return sorted(pants_run.stdout_data.split())

  def targets_for_shard(self, shard):
    if shard < 0 or shard >= self._SHARDS:
      raise Exception('Invalid shard: {} / {}'.format(shard, self._SHARDS))

    per_shard = int(math.ceil(len(self.targets) / self._SHARDS))
    offset = (per_shard * shard)
    return self.targets[offset:offset + per_shard]

  @ensure_resolver
  def run_shard(self, shard):
    targets = self.targets_for_shard(shard)
    pants_run = self.pants_test(targets + ['--jvm-platform-default-platform=java7',
                                           '--gen-protoc-import-from-root'])
    self.assert_success(pants_run)

  def test_self(self):
    self.assertEqual([t for s in range(0, self._SHARDS)
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

  def test_shard_16(self):
    self.run_shard(16)

  def test_shard_17(self):
    self.run_shard(17)

  def test_shard_18(self):
    self.run_shard(18)

  def test_shard_19(self):
    self.run_shard(19)

  def test_shard_20(self):
    self.run_shard(20)

  def test_shard_21(self):
    self.run_shard(21)

  def test_shard_22(self):
    self.run_shard(22)

  def test_shard_23(self):
    self.run_shard(23)

  def test_shard_24(self):
    self.run_shard(24)

  def test_shard_25(self):
    self.run_shard(25)

  def test_shard_26(self):
    self.run_shard(26)

  def test_shard_27(self):
    self.run_shard(27)

  def test_shard_28(self):
    self.run_shard(28)

  def test_shard_29(self):
    self.run_shard(29)

  def test_shard_30(self):
    self.run_shard(30)

  def test_shard_31(self):
    self.run_shard(31)

  def test_shard_32(self):
    self.run_shard(32)

  def test_shard_33(self):
    self.run_shard(33)

  def test_shard_34(self):
    self.run_shard(34)

  def test_shard_35(self):
    self.run_shard(35)

  def test_shard_36(self):
    self.run_shard(36)

  def test_shard_37(self):
    self.run_shard(37)

  def test_shard_38(self):
    self.run_shard(38)

  def test_shard_39(self):
    self.run_shard(39)

  def test_shard_40(self):
    self.run_shard(40)

  def test_shard_41(self):
    self.run_shard(41)

  def test_shard_42(self):
    self.run_shard(42)

  def test_shard_43(self):
    self.run_shard(43)

  def test_shard_44(self):
    self.run_shard(44)

  def test_shard_45(self):
    self.run_shard(45)

  def test_shard_46(self):
    self.run_shard(46)

  def test_shard_47(self):
    self.run_shard(47)

  def test_shard_48(self):
    self.run_shard(48)

  def test_shard_49(self):
    self.run_shard(49)

  def test_shard_50(self):
    self.run_shard(50)

  def test_shard_51(self):
    self.run_shard(51)

  def test_shard_52(self):
    self.run_shard(52)

  def test_shard_53(self):
    self.run_shard(53)

  def test_shard_54(self):
    self.run_shard(54)

  def test_shard_55(self):
    self.run_shard(55)

  def test_shard_56(self):
    self.run_shard(56)

  def test_shard_57(self):
    self.run_shard(57)

  def test_shard_58(self):
    self.run_shard(58)

  def test_shard_59(self):
    self.run_shard(59)

  def test_shard_60(self):
    self.run_shard(60)

  def test_shard_61(self):
    self.run_shard(61)

  def test_shard_62(self):
    self.run_shard(62)

  def test_shard_63(self):
    self.run_shard(63)
