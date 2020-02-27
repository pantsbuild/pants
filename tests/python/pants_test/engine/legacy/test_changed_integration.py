# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.testutil.git_util import create_isolated_git_repo, mutated_working_copy, create_file_in
from pants.testutil.pants_run_integration_test import (
    PantsRunIntegrationTest,
    ensure_daemon,
)
from pants.testutil.test_base import AbstractTestGenerator
from pants.util.dirutil import safe_delete, touch
from pants.util.strutil import lines_to_set


class ChangedIntegrationTest(PantsRunIntegrationTest, AbstractTestGenerator):

    TEST_MAPPING = {
        # A `jvm_binary` with `source='file.name'`.
        "src/java/org/pantsbuild/helloworld/helloworld.java": dict(
            none=["src/java/org/pantsbuild/helloworld:helloworld"],
            direct=["src/java/org/pantsbuild/helloworld:helloworld"],
            transitive=["src/java/org/pantsbuild/helloworld:helloworld"],
        ),
        # A `python_binary` with `source='file.name'`.
        "src/python/python_targets/test_binary.py": dict(
            none=["src/python/python_targets:test"],
            direct=["src/python/python_targets:test"],
            transitive=["src/python/python_targets:test"],
        ),
        # A `python_library` with `sources=['file.name']`.
        "src/python/python_targets/test_library.py": dict(
            none=["src/python/python_targets:test_library"],
            direct=[
                "src/python/python_targets:test",
                "src/python/python_targets:test_library",
                "src/python/python_targets:test_library_direct_dependee",
            ],
            transitive=[
                "src/python/python_targets:test",
                "src/python/python_targets:test_library",
                "src/python/python_targets:test_library_direct_dependee",
                "src/python/python_targets:test_library_transitive_dependee",
                "src/python/python_targets:test_library_transitive_dependee_2",
                "src/python/python_targets:test_library_transitive_dependee_3",
                "src/python/python_targets:test_library_transitive_dependee_4",
            ],
        ),
        # A `resources` target with `sources=['file.name']` referenced by a `java_library` target.
        "src/resources/org/pantsbuild/resourceonly/README.md": dict(
            none=["src/resources/org/pantsbuild/resourceonly:resource"],
            direct=[
                "src/java/org/pantsbuild/helloworld:helloworld",
                "src/resources/org/pantsbuild/resourceonly:resource",
            ],
            transitive=[
                "src/java/org/pantsbuild/helloworld:helloworld",
                "src/resources/org/pantsbuild/resourceonly:resource",
            ],
        ),
        # A `python_library` with `sources=['file.name'] .
        "src/python/sources/sources.py": dict(
            none=["src/python/sources:sources"],
            direct=["src/python/sources:sources"],
            transitive=["src/python/sources:sources"],
        ),
        # A `scala_library` with `sources=['file.name']`.
        "tests/scala/org/pantsbuild/cp-directories/ClasspathDirectoriesSpec.scala": dict(
            none=["tests/scala/org/pantsbuild/cp-directories:cp-directories"],
            direct=["tests/scala/org/pantsbuild/cp-directories:cp-directories"],
            transitive=["tests/scala/org/pantsbuild/cp-directories:cp-directories"],
        ),
        # A `go_binary` with default sources.
        "src/go/tester/main.go": dict(
            none=["src/go/tester:tester"],
            direct=["src/go/tester:tester"],
            transitive=["src/go/tester:tester"],
        ),
        # An unclaimed source file.
        "src/python/python_targets/test_unclaimed_src.py": dict(none=[], direct=[], transitive=[]),
    }

    @classmethod
    def generate_tests(cls):
        """Generates tests on the class for better reporting granularity than an opaque for loop
        test."""

        def safe_filename(f):
            return f.replace("/", "_").replace(".", "_")

        for filename, dependee_mapping in cls.TEST_MAPPING.items():
            for dependee_type in dependee_mapping.keys():
                # N.B. The parameters here are used purely to close over the respective loop variables.
                def inner_integration_coverage_test(
                    self, filename=filename, dependee_type=dependee_type
                ):
                    with create_isolated_git_repo() as worktree:
                        # Mutate the working copy so we can do `--changed-parent=HEAD` deterministically.
                        with mutated_working_copy([os.path.join(worktree, filename)]):
                            stdout = self.run_list(
                                [
                                    f"--changed-include-dependees={dependee_type}",
                                    "--changed-parent=HEAD",
                                ],
                            )

                            self.assertEqual(
                                lines_to_set(self.TEST_MAPPING[filename][dependee_type]),
                                lines_to_set(stdout),
                            )

                cls.add_test(
                    f"test_changed_coverage_{dependee_type}_{safe_filename(filename)}",
                    inner_integration_coverage_test,
                )

    def run_list(self, extra_args, success=True):
        list_args = ["-q", "list"] + extra_args
        pants_run = self.do_command(*list_args, success=success)
        return pants_run.stdout_data

    def test_changed_exclude_root_targets_only(self):
        changed_src = "src/python/python_targets/test_library.py"
        exclude_target_regexp = r"_[0-9]"
        excluded_set = {
            "src/python/python_targets:test_library_transitive_dependee_2",
            "src/python/python_targets:test_library_transitive_dependee_3",
            "src/python/python_targets:test_library_transitive_dependee_4",
        }
        expected_set = set(self.TEST_MAPPING[changed_src]["transitive"]) - excluded_set

        with create_isolated_git_repo() as worktree:
            with mutated_working_copy([os.path.join(worktree, changed_src)]):
                pants_run = self.run_pants(
                    [
                        "-ldebug",  # This ensures the changed target names show up in the pants output.
                        f"--exclude-target-regexp={exclude_target_regexp}",
                        "--changed-parent=HEAD",
                        "--changed-include-dependees=transitive",
                        "test",
                    ]
                )

            self.assert_success(pants_run)
            for expected_item in expected_set:
                self.assertIn(expected_item, pants_run.stdout_data)

            for excluded_item in excluded_set:
                self.assertNotIn(excluded_item, pants_run.stdout_data)

    def test_changed_not_exclude_inner_targets(self):
        changed_src = "src/python/python_targets/test_library.py"
        exclude_target_regexp = r"_[0-9]"
        excluded_set = {
            "src/python/python_targets:test_library_transitive_dependee_2",
            "src/python/python_targets:test_library_transitive_dependee_3",
            "src/python/python_targets:test_library_transitive_dependee_4",
        }
        expected_set = set(self.TEST_MAPPING[changed_src]["transitive"]) - excluded_set

        with create_isolated_git_repo() as worktree:
            with mutated_working_copy([os.path.join(worktree, changed_src)]):
                pants_run = self.run_pants(
                    [
                        "-ldebug",  # This ensures the changed target names show up in the pants output.
                        f"--exclude-target-regexp={exclude_target_regexp}",
                        "--changed-parent=HEAD",
                        "--changed-include-dependees=transitive",
                        "test",
                    ]
                )

            self.assert_success(pants_run)
            for expected_item in expected_set:
                self.assertIn(expected_item, pants_run.stdout_data)

            for excluded_item in excluded_set:
                self.assertNotIn(excluded_item, pants_run.stdout_data)

    def test_changed_with_multiple_build_files(self):
        new_build_file = "src/python/python_targets/BUILD.new"

        with create_isolated_git_repo() as worktree:
            touch(os.path.join(worktree, new_build_file))
            stdout_data = self.run_list([])
            self.assertEqual(stdout_data.strip(), "")

    def test_changed_with_deleted_source(self):
        with create_isolated_git_repo() as worktree:
            safe_delete(os.path.join(worktree, "src/python/sources/sources.py"))
            pants_run = self.run_pants(["list", "--changed-parent=HEAD"])
            self.assert_success(pants_run)
            self.assertEqual(pants_run.stdout_data.strip(), "src/python/sources:sources")

    def test_changed_with_deleted_resource(self):
        with create_isolated_git_repo() as worktree:
            safe_delete(os.path.join(worktree, "src/python/sources/sources.txt"))
            pants_run = self.run_pants(["list", "--changed-parent=HEAD"])
            self.assert_success(pants_run)
            self.assertEqual(pants_run.stdout_data.strip(), "src/python/sources:text")

    def test_changed_with_deleted_target_transitive(self):
        with create_isolated_git_repo() as worktree:
            safe_delete(os.path.join(worktree, "src/resources/org/pantsbuild/resourceonly/BUILD"))
            pants_run = self.run_pants(
                ["list", "--changed-parent=HEAD", "--changed-include-dependees=transitive"]
            )
            self.assert_failure(pants_run)
            self.assertRegex(
                pants_run.stderr_data, "src/resources/org/pantsbuild/resourceonly:.*did not exist"
            )

    def test_changed_in_directory_without_build_file(self):
        with create_isolated_git_repo() as worktree:
            create_file_in(worktree, "new-project/README.txt", "This is important.")
            pants_run = self.run_pants(["list", "--changed-parent=HEAD"])
            self.assert_success(pants_run)
            self.assertEqual(pants_run.stdout_data.strip(), "")

    @ensure_daemon
    def test_list_changed(self):
        deleted_file = "src/python/sources/sources.py"

        with create_isolated_git_repo() as worktree:
            safe_delete(os.path.join(worktree, deleted_file))
            pants_run = self.run_pants(["--changed-parent=HEAD", "list"])
            self.assert_success(pants_run)
            self.assertEqual(pants_run.stdout_data.strip(), "src/python/sources:sources")


ChangedIntegrationTest.generate_tests()
