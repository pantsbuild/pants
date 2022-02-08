# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path, PurePath
from textwrap import dedent
from typing import Iterator

import pytest

from pants.util.contextutil import environment_as, pushd
from pants.vcs.git import Git, GitException


def init_repo(remote_name: str, remote: PurePath) -> None:
    subprocess.check_call(["git", "init", "--initial-branch=main"])
    subprocess.check_call(["git", "config", "user.email", "you@example.com"])
    subprocess.check_call(["git", "config", "user.name", "Your Name"])
    subprocess.check_call(["git", "config", "commit.gpgSign", "false"])
    subprocess.check_call(["git", "remote", "add", remote_name, str(remote)])


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin"
    origin.mkdir()
    with pushd(origin.as_posix()):
        subprocess.check_call(["git", "init", "--bare", "--initial-branch=main"])
    return origin


@pytest.fixture
def gitdir(tmp_path: Path) -> Path:
    gitdir = tmp_path / "gitdir"
    gitdir.mkdir()
    return gitdir


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    wt = tmp_path / "worktree"
    wt.mkdir()
    return wt


@pytest.fixture
def readme_file(worktree: Path) -> Path:
    return worktree / "README"


@pytest.fixture
def git(origin: Path, gitdir: Path, worktree: Path, readme_file: Path) -> Git:
    with environment_as(GIT_DIR=str(gitdir), GIT_WORK_TREE=str(worktree)):
        init_repo("depot", origin)

        readme_file.touch()
        subprocess.check_call(["git", "add", "README"])
        subdir = worktree / "dir"
        subdir.mkdir()
        (subdir / "f").write_text("file in subdir")

        # Make some symlinks
        os.symlink("f", os.path.join(worktree, "dir", "relative-symlink"))
        os.symlink("no-such-file", os.path.join(worktree, "dir", "relative-nonexistent"))
        os.symlink("dir/f", os.path.join(worktree, "dir", "not-absolute\u2764"))
        os.symlink("../README", os.path.join(worktree, "dir", "relative-dotdot"))
        os.symlink("dir", os.path.join(worktree, "link-to-dir"))
        os.symlink("README/f", os.path.join(worktree, "not-a-dir"))
        os.symlink("loop1", os.path.join(worktree, "loop2"))
        os.symlink("loop2", os.path.join(worktree, "loop1"))

        subprocess.check_call(
            ["git", "add", "README", "dir", "loop1", "loop2", "link-to-dir", "not-a-dir"]
        )
        subprocess.check_call(["git", "commit", "-am", "initial commit with decode -> \x81b"])

        subprocess.check_call(["git", "tag", "first"])
        subprocess.check_call(["git", "push", "--tags", "depot", "main"])
        subprocess.check_call(["git", "branch", "--set-upstream-to", "depot/main"])

        readme_file.write_bytes("Hello World.\u2764".encode())
        subprocess.check_call(["git", "commit", "-am", "Update README."])

    return Git(gitdir=gitdir, worktree=worktree)


def test_integration(worktree: Path, readme_file: Path, git: Git) -> None:
    assert set() == git.changed_files()
    assert {"README"} == git.changed_files(from_commit="HEAD^")

    assert "main" == git.branch_name

    with readme_file.open(mode="a") as fp:
        fp.write("More data.")

    (worktree / "INSTALL").write_text("make install")

    assert {"README"} == git.changed_files()
    assert {"README", "INSTALL"} == git.changed_files(include_untracked=True)

    # Confirm that files outside of a given relative_to path are ignored
    assert set() == git.changed_files(relative_to="non-existent")


def test_detect_worktree(tmp_path: Path, origin: PurePath, git: Git) -> None:
    clone = tmp_path / "clone"
    clone.mkdir()
    with pushd(clone.as_posix()):
        init_repo("origin", origin)
        subprocess.check_call(["git", "pull", "--tags", "origin", "main:main"])

        def worktree_relative_to(cwd: str, expected: PurePath | None):
            # Given a cwd relative to the worktree, tests that the worktree is detected as
            # 'expected'.
            abs_cwd = clone / cwd
            abs_cwd.mkdir(parents=True, exist_ok=True)
            with pushd(str(abs_cwd)):
                actual = Git.mount().worktree
                assert expected == actual

        with pytest.raises(GitException):
            worktree_relative_to("..", None)
        worktree_relative_to(".", clone)
        worktree_relative_to("is", clone)
        worktree_relative_to("is/a", clone)
        worktree_relative_to("is/a/dir", clone)


def test_detect_worktree_no_cwd(tmp_path: Path, origin: PurePath, git: Git) -> None:
    clone = tmp_path / "clone"
    clone.mkdir()
    with pushd(clone.as_posix()):
        init_repo("origin", origin)
        subprocess.check_call(["git", "pull", "--tags", "origin", "main:main"])

        def worktree_relative_to(some_dir: str, expected: PurePath | None):
            # Given a directory relative to the worktree, tests that the worktree is detected as
            # 'expected'.
            subdir = clone / some_dir
            subdir.mkdir(parents=True, exist_ok=True)
            actual = Git.mount(subdir=subdir).worktree
            assert expected == actual

        with pytest.raises(GitException):
            worktree_relative_to("..", None)
        worktree_relative_to(".", clone)
        worktree_relative_to("is", clone)
        worktree_relative_to("is/a", clone)
        worktree_relative_to("is/a/dir", clone)


def test_changes_in(gitdir: PurePath, worktree: Path, git: Git) -> None:
    """Test finding changes in a diffspecs.

    To some extent this is just testing functionality of git not pants, since all pants says is that
    it will pass the diffspec to git diff-tree, but this should serve to at least document the
    functionality we believe works.
    """
    with environment_as(GIT_DIR=str(gitdir), GIT_WORK_TREE=str(worktree)):

        def commit_contents_to_files(content: str, *files: str) -> str:
            for path in files:
                (worktree / path).write_text(content)
            subprocess.check_call(["git", "add", "."])
            subprocess.check_call(["git", "commit", "-m", f"change {files}"])
            return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()

        # We can get changes in HEAD or by SHA
        c1 = commit_contents_to_files("1", "foo")
        assert {"foo"} == git.changes_in("HEAD")
        assert {"foo"} == git.changes_in(c1)

        # Changes in new HEAD, from old-to-new HEAD, in old HEAD, or from old-old-head to new.
        commit_contents_to_files("2", "bar")
        assert {"bar"} == git.changes_in("HEAD")
        assert {"bar"} == git.changes_in("HEAD^..HEAD")
        assert {"foo"} == git.changes_in("HEAD^")
        assert {"foo"} == git.changes_in("HEAD~1")
        assert {"foo", "bar"} == git.changes_in("HEAD^^..HEAD")

        # New commit doesn't change results-by-sha
        assert {"foo"} == git.changes_in(c1)

        # Files changed in multiple diffs within a range
        c3 = commit_contents_to_files("3", "foo")
        assert {"foo", "bar"} == git.changes_in(f"{c1}..{c3}")

        # Changes in a tag
        subprocess.check_call(["git", "tag", "v1"])
        assert {"foo"} == git.changes_in("v1")

        # Introduce a new filename
        c4 = commit_contents_to_files("4", "baz")
        assert {"baz"} == git.changes_in("HEAD")

        # Tag-to-sha
        assert {"baz"} == git.changes_in(f"v1..{c4}")

        # We can get multiple changes from one ref
        commit_contents_to_files("5", "foo", "bar")
        assert {"foo", "bar"} == git.changes_in("HEAD")
        assert {"foo", "bar", "baz"} == git.changes_in("HEAD~4..HEAD")
        assert {"foo", "bar", "baz"} == git.changes_in(f"{c1}..HEAD")
        assert {"foo", "bar", "baz"} == git.changes_in(f"{c1}..{c4}")


def test_commit_with_new_untracked_file_adds_file(worktree: Path, git: Git) -> None:
    new_file = worktree / "untracked_file"
    new_file.touch()

    assert {"untracked_file"} == git.changed_files(include_untracked=True)

    git.add(new_file)

    assert {"untracked_file"} == git.changed_files()

    git.commit("API Changes.")

    assert set() == git.changed_files(include_untracked=True)


def test_bad_ref_stderr_issues_13396(git: Git) -> None:
    with pytest.raises(GitException, match=re.escape("fatal: bad revision 'remote/dne...HEAD'\n")):
        git.changed_files(from_commit="remote/dne")

    with pytest.raises(
        GitException,
        match=re.escape(
            "fatal: ambiguous argument 'HEAD~1000': unknown revision or path not in the working "
            "tree.\n"
        ),
    ):
        git.changes_in(diffspec="HEAD~1000")


@pytest.fixture
def empty_path(tmp_path: Path) -> Iterator[Path]:
    bin = tmp_path / "bin"
    bin.mkdir()
    with environment_as(PATH=bin.as_posix()):
        yield bin


@pytest.fixture
def unexecutable_git(empty_path: Path) -> Path:
    git = empty_path / "git"
    git.touch()
    return git


@pytest.fixture
def executable_git(unexecutable_git: Path) -> Path:
    unexecutable_git.chmod(0o755)
    return unexecutable_git


def test_detect_worktree_no_git(empty_path: PurePath) -> None:
    with pytest.raises(GitException):
        Git.mount()


def test_detect_worktree_unexectuable_git(unexecutable_git: PurePath) -> None:
    with pytest.raises(GitException):
        Git.mount()
    with pytest.raises(GitException):
        Git.mount(binary=unexecutable_git)


def test_detect_worktree_invalid_executable_git(executable_git: PurePath) -> None:
    with pytest.raises(GitException):
        assert Git.mount() is None
    with pytest.raises(GitException):
        Git.mount(binary=executable_git)


def test_detect_worktree_failing_git(executable_git: Path) -> None:
    executable_git.write_text(
        dedent(
            """\
            #!/bin/sh
            exit 1
            """
        )
    )
    with pytest.raises(GitException):
        Git.mount()
    with pytest.raises(GitException):
        Git.mount(binary=executable_git)


def test_detect_worktree_working_git(executable_git: Path) -> None:
    expected_worktree_dir = PurePath("/a/fake/worktree/dir")
    executable_git.write_text(
        dedent(
            f"""\
            #!/bin/sh
            echo {expected_worktree_dir}
            """
        )
    )
    assert expected_worktree_dir == Git.mount().worktree
    assert expected_worktree_dir == Git.mount(binary=executable_git).worktree
