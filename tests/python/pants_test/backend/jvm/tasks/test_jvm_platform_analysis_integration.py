# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager
from textwrap import dedent

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class JvmPlatformAnalysisIntegrationTest(PantsRunIntegrationTest):
    """Make sure jvm-platform-analysis runs properly, especially with respect to caching
    behavior."""

    FAILURE_MESSAGE = "Dependencies cannot have a higher java target level than dependees!"
    CACHE_MESSAGE = "Invalidated 2 targets"

    class JavaSandbox:
        """Testing sandbox for making temporary java_library targets."""

        def __init__(self, test, workdir, javadir):
            self.javadir = javadir
            self.workdir = workdir
            self.test = test
            if not os.path.exists(self.workdir):
                os.makedirs(self.workdir)

        @property
        def build_file_path(self):
            return os.path.join(self.javadir, "BUILD")

        def write_build_file(self, contents):
            with open(self.build_file_path, "w") as f:
                f.write(contents)

        def spec(self, name):
            return f"{self.javadir}:{name}"

        def clean_all(self):
            return self.test.run_pants_with_workdir(["clean-all"], workdir=self.workdir)

        def jvm_platform_validate(self, *targets):
            return self.test.run_pants_with_workdir(
                ["jvm-platform-validate", "--check=fatal"] + list(map(self.spec, targets)),
                workdir=self.workdir,
            )

    @contextmanager
    def setup_sandbox(self):
        with temporary_dir(".") as sourcedir:
            with self.temporary_workdir() as workdir:
                javadir = os.path.join(sourcedir, "src", "java")
                os.makedirs(javadir)
                yield self.JavaSandbox(self, workdir, javadir)

    @property
    def _good_one_two(self):
        return dedent(
            """
            java_library(name='one',
              platform='java8',
            )

            java_library(name='two',
              platform='java9',
            )
            """
        )

    @property
    def _bad_one_two(self):
        return dedent(
            """
            java_library(name='one',
              platform='java8',
              dependencies=[':two'],
            )

            java_library(name='two',
              platform='java9',
            )
            """
        )

    def test_good_targets_works_fresh(self):
        with self.setup_sandbox() as sandbox:
            sandbox.write_build_file(self._good_one_two)
            self.assert_success(sandbox.clean_all())
            run = sandbox.jvm_platform_validate("one", "two")
            self.assert_success(run)

    def test_bad_targets_fails_fresh(self):
        with self.setup_sandbox() as sandbox:
            sandbox.write_build_file(self._bad_one_two)
            self.assert_success(sandbox.clean_all())
            run = sandbox.jvm_platform_validate("one", "two")
            self.assert_failure(run)
            self.assertIn(self.FAILURE_MESSAGE, run.stdout_data)

    def test_good_then_bad(self):
        with self.setup_sandbox() as sandbox:
            sandbox.write_build_file(self._good_one_two)
            self.assert_success(sandbox.clean_all())
            good_run = sandbox.jvm_platform_validate("one", "two")
            self.assert_success(good_run)
            sandbox.write_build_file(self._bad_one_two)
            bad_run = sandbox.jvm_platform_validate("one", "two")
            self.assert_failure(bad_run)
            self.assertIn(self.FAILURE_MESSAGE, bad_run.stdout_data)

    def test_bad_then_good(self):
        with self.setup_sandbox() as sandbox:
            sandbox.write_build_file(self._bad_one_two)
            self.assert_success(sandbox.clean_all())
            bad_run = sandbox.jvm_platform_validate("one", "two")
            self.assert_failure(bad_run)
            self.assertIn(self.FAILURE_MESSAGE, bad_run.stdout_data)
            sandbox.write_build_file(self._good_one_two)
            good_run = sandbox.jvm_platform_validate("one", "two")
            self.assert_success(good_run)

    def test_good_caching(self):
        # Make sure targets are cached after a good run.
        with self.setup_sandbox() as sandbox:
            sandbox.write_build_file(self._good_one_two)
            self.assert_success(sandbox.clean_all())
            first_run = sandbox.jvm_platform_validate("one", "two")
            self.assert_success(first_run)
            self.assertIn(self.CACHE_MESSAGE, first_run.stdout_data)
            second_run = sandbox.jvm_platform_validate("one", "two")
            self.assert_success(second_run)
            self.assertNotIn(self.CACHE_MESSAGE, second_run.stdout_data)

    def test_bad_caching(self):
        # Make sure targets aren't cached after a bad run.
        with self.setup_sandbox() as sandbox:
            sandbox.write_build_file(self._bad_one_two)
            self.assert_success(sandbox.clean_all())
            first_run = sandbox.jvm_platform_validate("one", "two")
            self.assert_failure(first_run)
            self.assertIn(self.CACHE_MESSAGE, first_run.stdout_data)
            second_run = sandbox.jvm_platform_validate("one", "two")
            self.assert_failure(second_run)
            self.assertIn(self.CACHE_MESSAGE, second_run.stdout_data)
