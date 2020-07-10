# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import unittest
from contextlib import contextmanager

from pants.scm.git import Git
from pants.util.contextutil import environment_as, pushd, temporary_dir
from pants.util.dirutil import chmod_plus_x, safe_mkdir, safe_mkdtemp, safe_open, safe_rmtree, touch


class GitTest(unittest.TestCase):
    @staticmethod
    def init_repo(remote_name, remote):
        # TODO (peiyu) clean this up, use `git_util.initialize_repo`.
        subprocess.check_call(["git", "init"])
        subprocess.check_call(["git", "config", "user.email", "you@example.com"])
        subprocess.check_call(["git", "config", "user.name", "Your Name"])
        subprocess.check_call(["git", "config", "commit.gpgSign", "false"])
        subprocess.check_call(["git", "remote", "add", remote_name, remote])

    def setUp(self):
        self.origin = safe_mkdtemp()
        with pushd(self.origin):
            subprocess.check_call(["git", "init", "--bare"])

        self.gitdir = safe_mkdtemp()
        self.worktree = safe_mkdtemp()

        self.readme_file = os.path.join(self.worktree, "README")

        with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
            self.init_repo("depot", self.origin)

            touch(self.readme_file)
            subprocess.check_call(["git", "add", "README"])
            safe_mkdir(os.path.join(self.worktree, "dir"))
            with open(os.path.join(self.worktree, "dir", "f"), "w") as f:
                f.write("file in subdir")

            # Make some symlinks
            os.symlink("f", os.path.join(self.worktree, "dir", "relative-symlink"))
            os.symlink("no-such-file", os.path.join(self.worktree, "dir", "relative-nonexistent"))
            os.symlink("dir/f", os.path.join(self.worktree, "dir", "not-absolute\u2764"))
            os.symlink("../README", os.path.join(self.worktree, "dir", "relative-dotdot"))
            os.symlink("dir", os.path.join(self.worktree, "link-to-dir"))
            os.symlink("README/f", os.path.join(self.worktree, "not-a-dir"))
            os.symlink("loop1", os.path.join(self.worktree, "loop2"))
            os.symlink("loop2", os.path.join(self.worktree, "loop1"))

            subprocess.check_call(
                ["git", "add", "README", "dir", "loop1", "loop2", "link-to-dir", "not-a-dir"]
            )
            subprocess.check_call(["git", "commit", "-am", "initial commit with decode -> \x81b"])
            self.initial_rev = subprocess.check_output(["git", "rev-parse", "HEAD"]).strip()
            subprocess.check_call(["git", "tag", "first"])
            subprocess.check_call(["git", "push", "--tags", "depot", "master"])
            subprocess.check_call(["git", "branch", "--set-upstream-to", "depot/master"])

            with safe_open(self.readme_file, "wb") as readme:
                readme.write("Hello World.\u2764".encode())
            subprocess.check_call(["git", "commit", "-am", "Update README."])

            self.current_rev = subprocess.check_output(["git", "rev-parse", "HEAD"]).strip()

        self.clone2 = safe_mkdtemp()
        with pushd(self.clone2):
            self.init_repo("origin", self.origin)
            subprocess.check_call(["git", "pull", "--tags", "origin", "master:master"])

            with safe_open(os.path.realpath("README"), "a") as readme:
                readme.write("--")
            subprocess.check_call(["git", "commit", "-am", "Update README 2."])
            subprocess.check_call(["git", "push", "--tags", "origin", "master"])

        self.git = Git(gitdir=self.gitdir, worktree=self.worktree)

    def tearDown(self):
        safe_rmtree(self.origin)
        safe_rmtree(self.gitdir)
        safe_rmtree(self.worktree)
        safe_rmtree(self.clone2)

    def test_integration(self):
        self.assertEqual(set(), self.git.changed_files())
        self.assertEqual({"README"}, self.git.changed_files(from_commit="HEAD^"))

        tip_sha = self.git.commit_id
        self.assertTrue(tip_sha)
        self.assertEqual("master", self.git.branch_name)

        def edit_readme():
            with open(self.readme_file, "a") as fp:
                fp.write("More data.")

        edit_readme()
        with open(os.path.join(self.worktree, "INSTALL"), "w") as untracked:
            untracked.write("make install")
        self.assertEqual({"README"}, self.git.changed_files())
        self.assertEqual({"README", "INSTALL"}, self.git.changed_files(include_untracked=True))

        # Confirm that files outside of a given relative_to path are ignored
        self.assertEqual(set(), self.git.changed_files(relative_to="non-existent"))

    def test_detect_worktree(self):
        with temporary_dir() as _clone:
            with pushd(_clone):
                clone = os.path.realpath(_clone)

                self.init_repo("origin", self.origin)
                subprocess.check_call(["git", "pull", "--tags", "origin", "master:master"])

                def worktree_relative_to(cwd, expected):
                    # Given a cwd relative to the worktree, tests that the worktree is detected as 'expected'.
                    orig_cwd = os.getcwd()
                    try:
                        abs_cwd = os.path.join(clone, cwd)
                        if not os.path.isdir(abs_cwd):
                            os.mkdir(abs_cwd)
                        os.chdir(abs_cwd)
                        actual = Git.detect_worktree()
                        self.assertEqual(expected, actual)
                    finally:
                        os.chdir(orig_cwd)

                worktree_relative_to("..", None)
                worktree_relative_to(".", clone)
                worktree_relative_to("is", clone)
                worktree_relative_to("is/a", clone)
                worktree_relative_to("is/a/dir", clone)

    def test_detect_worktree_no_cwd(self):
        with temporary_dir() as _clone:
            with pushd(_clone):
                clone = os.path.realpath(_clone)

                self.init_repo("origin", self.origin)
                subprocess.check_call(["git", "pull", "--tags", "origin", "master:master"])

                def worktree_relative_to(some_dir, expected):
                    # Given a directory relative to the worktree, tests that the worktree is detected as 'expected'.
                    subdir = os.path.join(clone, some_dir)
                    if not os.path.isdir(subdir):
                        os.mkdir(subdir)
                    actual = Git.detect_worktree(subdir=subdir)
                    self.assertEqual(expected, actual)

                worktree_relative_to("..", None)
                worktree_relative_to(".", clone)
                worktree_relative_to("is", clone)
                worktree_relative_to("is/a", clone)
                worktree_relative_to("is/a/dir", clone)

    @property
    def test_changes_in(self):
        """Test finding changes in a diffspecs.

        To some extent this is just testing functionality of git not pants, since all pants says is
        that it will pass the diffspec to git diff-tree, but this should serve to at least document
        the functionality we believe works.
        """
        with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):

            def commit_contents_to_files(content, *files):
                for path in files:
                    with safe_open(os.path.join(self.worktree, path), "w") as fp:
                        fp.write(content)
                subprocess.check_call(["git", "add", "."])
                subprocess.check_call(["git", "commit", "-m", f"change {files}"])
                return subprocess.check_output(["git", "rev-parse", "HEAD"]).strip()

            # We can get changes in HEAD or by SHA
            c1 = commit_contents_to_files("1", "foo")
            self.assertEqual({"foo"}, self.git.changes_in("HEAD"))
            self.assertEqual({"foo"}, self.git.changes_in(c1))

            # Changes in new HEAD, from old-to-new HEAD, in old HEAD, or from old-old-head to new.
            commit_contents_to_files("2", "bar")
            self.assertEqual({"bar"}, self.git.changes_in("HEAD"))
            self.assertEqual({"bar"}, self.git.changes_in("HEAD^..HEAD"))
            self.assertEqual({"foo"}, self.git.changes_in("HEAD^"))
            self.assertEqual({"foo"}, self.git.changes_in("HEAD~1"))
            self.assertEqual({"foo", "bar"}, self.git.changes_in("HEAD^^..HEAD"))

            # New commit doesn't change results-by-sha
            self.assertEqual({"foo"}, self.git.changes_in(c1))

            # Files changed in multiple diffs within a range
            c3 = commit_contents_to_files("3", "foo")
            self.assertEqual({"foo", "bar"}, self.git.changes_in(f"{c1}..{c3}"))

            # Changes in a tag
            subprocess.check_call(["git", "tag", "v1"])
            self.assertEqual({"foo"}, self.git.changes_in("v1"))

            # Introduce a new filename
            c4 = commit_contents_to_files("4", "baz")
            self.assertEqual({"baz"}, self.git.changes_in("HEAD"))

            # Tag-to-sha
            self.assertEqual({"baz"}, self.git.changes_in(f"v1..{c4}"))

            # We can get multiple changes from one ref
            commit_contents_to_files("5", "foo", "bar")
            self.assertEqual({"foo", "bar"}, self.git.changes_in("HEAD"))
            self.assertEqual({"foo", "bar", "baz"}, self.git.changes_in("HEAD~4..HEAD"))
            self.assertEqual({"foo", "bar", "baz"}, self.git.changes_in(f"{c1}..HEAD"))
            self.assertEqual({"foo", "bar", "baz"}, self.git.changes_in(f"{c1}..{c4}"))

    def test_commit_with_new_untracked_file_adds_file(self):
        new_file = os.path.join(self.worktree, "untracked_file")

        touch(new_file)

        self.assertEqual({"untracked_file"}, self.git.changed_files(include_untracked=True))

        self.git.add(new_file)

        self.assertEqual({"untracked_file"}, self.git.changed_files())

        self.git.commit("API Changes.")

        self.assertEqual(set(), self.git.changed_files(include_untracked=True))


class DetectWorktreeFakeGitTest(unittest.TestCase):
    @contextmanager
    def empty_path(self):
        with temporary_dir() as path:
            with environment_as(PATH=path):
                yield path

    @contextmanager
    def unexecutable_git(self):
        with self.empty_path() as path:
            git = os.path.join(path, "git")
            touch(git)
            yield git

    @contextmanager
    def executable_git(self):
        with self.unexecutable_git() as git:
            chmod_plus_x(git)
            yield git

    def test_detect_worktree_no_git(self):
        with self.empty_path():
            self.assertIsNone(Git.detect_worktree())

    def test_detect_worktree_unexectuable_git(self):
        with self.unexecutable_git() as git:
            self.assertIsNone(Git.detect_worktree())
            self.assertIsNone(Git.detect_worktree(binary=git))

    def test_detect_worktree_invalid_executable_git(self):
        with self.executable_git() as git:
            self.assertIsNone(Git.detect_worktree())
            self.assertIsNone(Git.detect_worktree(binary=git))

    def test_detect_worktree_failing_git(self):
        with self.executable_git() as git:
            with open(git, "w") as fp:
                fp.write("#!/bin/sh\n")
                fp.write("exit 1")
            self.assertIsNone(Git.detect_worktree())
            self.assertIsNone(Git.detect_worktree(git))

    def test_detect_worktree_working_git(self):
        expected_worktree_dir = "/a/fake/worktree/dir"
        with self.executable_git() as git:
            with open(git, "w") as fp:
                fp.write("#!/bin/sh\n")
                fp.write("echo " + expected_worktree_dir)
            self.assertEqual(expected_worktree_dir, Git.detect_worktree())
            self.assertEqual(expected_worktree_dir, Git.detect_worktree(binary=git))
