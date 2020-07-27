# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
from contextlib import contextmanager
from textwrap import dedent

import pytest
from pants.base.build_environment import get_buildroot
from pants.testutil.git_util import initialize_repo
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon
from pants.testutil.test_base import AbstractTestGenerator
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_delete, safe_mkdir, safe_open, touch


def lines_to_set(str_or_list):
    if isinstance(str_or_list, list):
        return set(str_or_list)
    else:
        return {x for x in str(str_or_list).split("\n") if x}


def create_file_in(worktree, path, content):
    """Creates a file in the given worktree, and returns its path."""
    write_path = os.path.join(worktree, path)
    with safe_open(write_path, "w") as f:
        f.write(dedent(content))
    return write_path


@contextmanager
def mutated_working_copy(files_to_mutate, to_append="\n "):
    """Given a list of files, append whitespace to each of them to trigger a git diff - then reset."""
    assert to_append, "to_append may not be empty"

    for f in files_to_mutate:
        with open(f, "a") as fh:
            fh.write(to_append)
    try:
        yield
    finally:
        seek_point = len(to_append) * -1
        for f in files_to_mutate:
            with open(f, "ab") as fh:
                fh.seek(seek_point, os.SEEK_END)
                fh.truncate()


@contextmanager
def create_isolated_git_repo():
    # Isolated Git Repo Structure:
    # worktree
    # |--README
    # |--pants.toml
    # |--src
    #    |--resources
    #       |--org/pantsbuild/resourceonly
    #          |--BUILD
    #          |--README.md
    #    |--python
    #       |--python_targets
    #          |--BUILD
    #          |--test_binary.py
    #          |--test_library.py
    #          |--test_unclaimed_src.py
    #       |--sources
    #          |--BUILD
    #          |--sources.py
    #          |--sources.txt
    with temporary_dir(root_dir=get_buildroot()) as worktree:

        def create_file(path, content):
            """Creates a file in the isolated git repo."""
            return create_file_in(worktree, path, content)

        def copy_into(path, to_path=None):
            """Copies a file from the real git repo into the isolated git repo."""
            write_path = os.path.join(worktree, to_path or path)
            if os.path.isfile(path):
                safe_mkdir(os.path.dirname(write_path))
                shutil.copyfile(path, write_path)
            else:
                shutil.copytree(path, write_path)
            return write_path

        create_file("README", "N.B. This is just a test tree.")
        create_file(
            "pants.toml",
            f"""
            [GLOBAL]
            pythonpath = ["{get_buildroot()}/pants-plugins/src/python"]
            backend_packages2.add = ["pants.backend.python", "internal_backend.utilities"]
            """,
        )
        copy_into(".gitignore")

        with initialize_repo(worktree=worktree, gitdir=os.path.join(worktree, ".git")) as git:

            def add_to_git(commit_msg, *files):
                git.add(*files)
                git.commit(commit_msg)

            add_to_git(
                "resource file",
                create_file(
                    "src/resources/org/pantsbuild/resourceonly/BUILD",
                    """
                    resources(
                      name='resource',
                      sources=['README.md']
                    )
                    """,
                ),
                create_file(
                    "src/resources/org/pantsbuild/resourceonly/README.md", "Just a resource."
                ),
            )

            add_to_git(
                "python targets",
                copy_into("testprojects/src/python/python_targets", "src/python/python_targets"),
            )

            add_to_git(
                'a python_library with resources=["filename"]',
                copy_into("testprojects/src/python/sources", "src/python/sources"),
            )

            with environment_as(PANTS_BUILDROOT_OVERRIDE=worktree):
                yield worktree


class ChangedIntegrationTest(PantsRunIntegrationTest, AbstractTestGenerator):

    # TODO(#10355): Once we teach `dependees` to understand generated subtargets, some of these
    #  should change to be generated subtargets.
    TEST_MAPPING = {
        # A `python_binary` with `sources=['file.name']`.
        "src/python/python_targets/test_binary.py": dict(
            none=["src/python/python_targets/test_binary.py"],
            direct=["src/python/python_targets:test"],
            transitive=["src/python/python_targets:test"],
        ),
        # A `python_library` with `sources=['file.name']`.
        "src/python/python_targets/test_library.py": dict(
            none=["src/python/python_targets/test_library.py"],
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
        # A `python_library` with `sources=['file.name'] .
        "src/python/sources/sources.py": dict(
            none=["src/python/sources/sources.py"],
            direct=["src/python/sources:sources"],
            transitive=["src/python/sources:sources"],
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
                        # Mutate the working copy so we can do `--changed-since=HEAD` deterministically.
                        with mutated_working_copy([os.path.join(worktree, filename)]):
                            stdout = self.run_list(
                                [f"--changed-dependees={dependee_type}", "--changed-since=HEAD"],
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
        pants_run = self.do_command("list", *extra_args, success=success)
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
                # Making sure workdir is under buildroot
                with temporary_dir(root_dir=worktree, suffix=".pants.d") as workdir:
                    pants_run = self.run_pants_with_workdir(
                        command=[
                            f"--exclude-target-regexp={exclude_target_regexp}",
                            "--changed-since=HEAD",
                            "--changed-dependees=transitive",
                            "list",
                        ],
                        workdir=workdir,
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
                # Making sure workdir is under buildroot
                with temporary_dir(root_dir=worktree, suffix=".pants.d") as workdir:
                    pants_run = self.run_pants_with_workdir(
                        [
                            f"--exclude-target-regexp={exclude_target_regexp}",
                            "--changed-since=HEAD",
                            "--changed-dependees=transitive",
                            "list",
                        ],
                        workdir=workdir,
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
            pants_run = self.run_pants(["list", "--changed-since=HEAD"])
            self.assert_success(pants_run)
            self.assertEqual(pants_run.stdout_data.strip(), "src/python/sources:sources")

    def test_changed_with_deleted_resource(self):
        with create_isolated_git_repo() as worktree:
            safe_delete(os.path.join(worktree, "src/python/sources/sources.txt"))
            pants_run = self.run_pants(["list", "--changed-since=HEAD"])
            self.assert_success(pants_run)
            self.assertEqual(pants_run.stdout_data.strip(), "src/python/sources:text")

    @pytest.mark.skip(reason="Unskip after rewriting these tests to stop using testprojects.")
    def test_changed_with_deleted_target_transitive(self):
        # TODO: The deleted target should be a dependee of another target. We want to make sure
        # that this causes a crash because the dependee can't find it's dependency.
        with create_isolated_git_repo() as worktree:
            safe_delete(os.path.join(worktree, "src/resources/org/pantsbuild/resourceonly/BUILD"))
            pants_run = self.run_pants(
                ["list", "--changed-since=HEAD", "--changed-dependees=transitive"]
            )
            self.assert_failure(pants_run)
            self.assertRegex(
                pants_run.stderr_data, "src/resources/org/pantsbuild/resourceonly:.*did not exist"
            )

    def test_changed_in_directory_without_build_file(self):
        with create_isolated_git_repo() as worktree:
            create_file_in(worktree, "new-project/README.txt", "This is important.")
            pants_run = self.run_pants(["list", "--changed-since=HEAD"])
            self.assert_success(pants_run)
            self.assertEqual(pants_run.stdout_data.strip(), "")

    @ensure_daemon
    def test_list_changed(self):
        deleted_file = "src/python/sources/sources.py"

        with create_isolated_git_repo() as worktree:
            safe_delete(os.path.join(worktree, deleted_file))
            pants_run = self.run_pants(["--changed-since=HEAD", "list"])
            self.assert_success(pants_run)
            self.assertEqual(pants_run.stdout_data.strip(), "src/python/sources:sources")


ChangedIntegrationTest.generate_tests()
