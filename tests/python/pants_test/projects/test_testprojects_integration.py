# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import math

from pants.util.memo import memoized_property
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.test_base import AbstractTestGenerator


class TestProjectsIntegrationTest(PantsRunIntegrationTest, AbstractTestGenerator):
    # To avoid having a single test method which covers all of `testprojects` (which
    # would run for a very long time with no output, and be more difficult to iterate
    # on), we shard all of the targets under `testprojects` into _SHARDS test methods.
    _SHARDS = 256

    @memoized_property
    def targets(self):
        """A sequence of target name strings."""

        # Targets that fail but shouldn't
        known_failing_targets = [
            # The following two targets lose out due to a resource collision, because `example_b` happens
            # to be first in the context, and test.junit mixes all classpaths.
            "testprojects/maven_layout/resource_collision/example_b/src/test/java/org/pantsbuild/duplicateres/exampleb:exampleb",
            "testprojects/maven_layout/resource_collision/example_c/src/test/java/org/pantsbuild/duplicateres/examplec:examplec",
            # TODO: This one has a missing dependency, but is intended to succeed... should it?
            "testprojects/src/java/org/pantsbuild/testproject/thriftdeptest",
            # TODO(Eric Ayers): I don't understand why this fails
            "testprojects/src/java/org/pantsbuild/testproject/jvmprepcommand:compile-prep-command",
            # TODO(#7903): failing to find -ltensorflow_framework
            "examples/src/python/example/tensorflow_custom_op:tensorflow-zero-out-op",
            "examples/src/python/example/tensorflow_custom_op:tensorflow-zero-out-op-wrapper",
            "examples/src/python/example/tensorflow_custom_op:tensorflow_custom_op",
            "examples/tests/python/example_test/tensorflow_custom_op:tensorflow_custom_op",
        ]

        # Targets that are intended to fail
        negative_test_targets = [
            "testprojects/maven_layout/provided_patching/leaf:fail",
            "testprojects/src/antlr/python/test:antlr_failure",
            "testprojects/src/java/org/pantsbuild/testproject/bundle:missing-files",
            "testprojects/src/java/org/pantsbuild/testproject/compilation_warnings:fatal",
            "testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target",
            "testprojects/src/java/org/pantsbuild/testproject/junit/earlyexit:tests",
            "testprojects/src/java/org/pantsbuild/testproject/junit/failing/tests/org/pantsbuild/tmp/tests",
            "testprojects/src/java/org/pantsbuild/testproject/junit/mixed/tests/org/pantsbuild/tmp/tests",
            "testprojects/src/java/org/pantsbuild/testproject/missingdepswhitelist.*",
            "testprojects/src/java/org/pantsbuild/testproject/missingdirectdepswhitelist:missingdirectdepswhitelist",
            "testprojects/src/java/org/pantsbuild/testproject/missingjardepswhitelist:missingjardepswhitelist",
            "testprojects/src/java/org/pantsbuild/testproject/runtime:compile-fail",
            "testprojects/src/scala/org/pantsbuild/testproject/compilation_failure",
            "testprojects/src/scala/org/pantsbuild/testproject/compilation_warnings:fatal",
            "testprojects/src/thrift/org/pantsbuild/thrift_exports:C-without-exports",
            "testprojects/src/thrift/org/pantsbuild/thrift_linter:",
            "testprojects/src/java/org/pantsbuild/testproject/provided:c",
            "testprojects/tests/java/org/pantsbuild/testproject/dummies:failing_target",
            "testprojects/tests/java/org/pantsbuild/testproject/empty:",
            "testprojects/tests/java/org/pantsbuild/testproject/fail256:fail256",
            "testprojects/tests/python/pants/dummies:failing_target",
            "testprojects/tests/scala/org/pantsbuild/testproject/non_exports:C",
            "testprojects/src/scala/org/pantsbuild/testproject/exclude_direct_dep",
            "testprojects/src/python/bad_requirements:badreq",
            "testprojects/src/python/bad_requirements:use_badreq",
            "testprojects/tests/python/pants/timeout:terminates_self",
            # These don't pass without special config.
            "testprojects/tests/java/org/pantsbuild/testproject/depman:new-tests",
            "testprojects/tests/java/org/pantsbuild/testproject/depman:old-tests",
            "testprojects/tests/java/org/pantsbuild/testproject/htmlreport:htmlreport",
            "testprojects/tests/java/org/pantsbuild/testproject/parallel.*",
            "testprojects/src/python/python_distribution/fasthello_with_install_requires.*",
            "testprojects/src/python/unicode/compilation_failure",
        ]

        # May not succeed without java8 installed
        need_java_8 = [
            "testprojects/src/java/org/pantsbuild/testproject/targetlevels/java8",
            "testprojects/tests/java/org/pantsbuild/testproject/testjvms",
            "testprojects/tests/java/org/pantsbuild/testproject/testjvms:eight",
            "testprojects/tests/java/org/pantsbuild/testproject/testjvms:eight-test-platform",
            "examples/src/java/org/pantsbuild/example/plugin",
        ]

        # Interpreter will not resolve correctly when Pants is constrained to Python 3
        python2_only = [
            # tested in test_antlr_py_gen_integration.py
            "testprojects/src/python/antlr"
        ]

        # Targets for testing timeouts. These should only be run during specific integration tests,
        # because they take a long time to run.
        timeout_targets = [
            "testprojects/tests/python/pants/timeout:sleeping_target",
            "testprojects/tests/java/org/pantsbuild/testproject/timeout:sleeping_target",
            # Called with test_pytest_run_integration
            "testprojects/tests/python/pants/timeout:exceeds_timeout",
            "testprojects/tests/python/pants/timeout:ignores_terminate",
        ]

        deliberately_conflicting_targets = ["testprojects/src/python/interpreter_selection.*"]

        simply_skip = [
            # Already tested at pants_test.backend.jvm.targets.test_jar_dependency_integration.JarDependencyIntegrationTest
            "testprojects/3rdparty/org/pantsbuild/testprojects:testprojects",
            # Already tested in 'PantsRequirementIntegrationTest' and 'SetupPyIntegrationTest'.
            "testprojects/pants-plugins/*",
            "testprojects/src/python/python_distribution/ctypes:ctypes_test",
            "testprojects/src/python/python_distribution/ctypes_with_third_party:ctypes_test",
            "testprojects/src/python/python_distribution/ctypes_with_extra_compiler_flags:bin",
            # Requires non-standard settings, and already tested by `ProtobufIntegrationTest.test_import_from_buildroot`
            "testprojects/src/protobuf/org/pantsbuild/testproject/import_from_buildroot.*",
        ]

        targets_to_exclude = (
            known_failing_targets
            + negative_test_targets
            + need_java_8
            + python2_only
            + timeout_targets
            + deliberately_conflicting_targets
            + simply_skip
        )
        exclude_opts = [
            "--exclude-target-regexp={}".format(target) for target in targets_to_exclude
        ]

        # Run list with exclude options, then parse and sort output.
        pants_run = self.run_pants(["list", "testprojects::", "examples::"] + exclude_opts)
        self.assert_success(pants_run)
        return sorted(pants_run.stdout_data.split())

    def targets_for_shard(self, shard):
        if shard < 0 or shard >= self._SHARDS:
            raise Exception("Invalid shard: {} / {}".format(shard, self._SHARDS))

        per_shard = int(math.ceil(len(self.targets) / self._SHARDS))
        offset = per_shard * shard
        return self.targets[offset : offset + per_shard]

    def run_shard(self, shard):
        targets = self.targets_for_shard(shard)
        pants_run = self.run_pants(["test"] + targets + ["--jvm-platform-default-platform=java7"])
        self.assert_success(pants_run)

    def test_self(self):
        self.assertEqual(
            [t for s in range(0, self._SHARDS) for t in self.targets_for_shard(s)], self.targets
        )

    @classmethod
    def generate_tests(cls):
        for shardid in range(0, cls._SHARDS):
            cls.add_test(f"test_shard_{shardid}", lambda this: this.run_shard(shardid))


TestProjectsIntegrationTest.generate_tests()
