# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class ProjectsTestBase(PantsRunIntegrationTest):
    @property
    def skipped_targets(self) -> List[str]:
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
            # Already tested at
            # pants_test.backend.jvm.targets.test_jar_dependency_integration.JarDependencyIntegrationTest
            "testprojects/3rdparty/org/pantsbuild/testprojects:testprojects",
            # Already tested in 'PantsRequirementIntegrationTest' and 'SetupPyIntegrationTest'.
            "testprojects/pants-plugins/*",
            "testprojects/src/python/python_distribution/ctypes:ctypes_test",
            "testprojects/src/python/python_distribution/ctypes_with_third_party:ctypes_test",
            "testprojects/src/python/python_distribution/ctypes_with_extra_compiler_flags:bin",
            # Requires non-standard settings, and already tested by
            # `ProtobufIntegrationTest.test_import_from_buildroot`
            "testprojects/src/protobuf/org/pantsbuild/testproject/import_from_buildroot.*",
        ]

        # E.g. tests depend on src/python or tests/python. This is only meant to be a temporary
        # workaround to unblock remoting integration tests.
        chroot_problems = [
            "examples/src/python/example/pants_publish_plugin:pants-publish-plugin",
        ]

        return [
            *known_failing_targets,
            *negative_test_targets,
            *timeout_targets,
            *deliberately_conflicting_targets,
            *simply_skip,
            *chroot_problems,
        ]

    @property
    def skipped_target_types(self) -> List[str]:
        """We don't want to run over every single target, e.g. files() are only used for us to
        depend on in ITs and it doesn't make sense to run `./pants test` against them."""
        return [
            # resources / loose files
            "files",
            "resources",
            "page",
            # 3rd-party dependencies
            "jar_library",
            "python_requirement_library",
        ]

    def targets_for_globs(self, *globs: str) -> List[str]:
        """A sequence of target name strings."""
        exclude_opts = [f"--exclude-target-regexp={target}" for target in self.skipped_targets]
        skipped_targets_opt = f"--filter-type=-{','.join(self.skipped_target_types)}"
        pants_run = self.run_pants(["filter", skipped_targets_opt, *globs, *exclude_opts])
        self.assert_success(pants_run)
        return list(sorted(pants_run.stdout_data.split()))

    def assert_valid_projects(self, *globs: str) -> None:
        pants_run = self.run_pants(["compile", "lint", "test", *self.targets_for_globs(*globs)])
        self.assert_success(pants_run)
