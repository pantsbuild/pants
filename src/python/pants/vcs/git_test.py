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

from pants.core.util_rules.system_binaries import GitBinary, GitBinaryException, MaybeGitBinary
from pants.engine.rules import Get, rule
from pants.testutil.rule_runner import QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.contextutil import environment_as, pushd
from pants.util.dirutil import touch
from pants.util.frozendict import FrozenDict
from pants.vcs.git import (
    DiffParser,
    GitWorktree,
    GitWorktreeRequest,
    MaybeGitWorktree,
    get_git_worktree,
)
from pants.vcs.hunk import Hunk, TextBlock


def init_repo(remote_name: str, remote: PurePath) -> None:
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["git", "symbolic-ref", "HEAD", "refs/heads/main"])
    subprocess.check_call(["git", "config", "user.email", "you@example.com"])
    subprocess.check_call(["git", "config", "user.name", "Your Name"])
    subprocess.check_call(["git", "remote", "add", remote_name, str(remote)])


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin"
    origin.mkdir()
    with pushd(origin.as_posix()):
        subprocess.check_call(["git", "init", "--bare"])
        subprocess.check_call(["git", "symbolic-ref", "HEAD", "refs/heads/main"])
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


def git_worktree(
    gitdir: os.PathLike[str] | None = None,
    subdir: os.PathLike[str] | None = None,
    binary: os.PathLike[str] = PurePath("git"),
) -> GitWorktree | None:
    maybe_git_worktree: MaybeGitWorktree = run_rule_with_mocks(
        rule=get_git_worktree,
        rule_args=[
            GitWorktreeRequest(gitdir=gitdir, subdir=subdir),
            MaybeGitBinary(git_binary=GitBinary(path=str(binary))),
        ],
    )

    return maybe_git_worktree.git_worktree


class MutatingGitWorktree(GitWorktree):
    def commit(self, message: str) -> None:
        self._git_binary._invoke_unsandboxed(
            self._create_git_cmdline(["commit", "--all", "--message", message])
        )

    def add(self, *paths: PurePath) -> None:
        self._git_binary._invoke_unsandboxed(
            self._create_git_cmdline(["add", *(str(path) for path in paths)])
        )


@pytest.fixture
def git(
    origin: Path, gitdir: Path, worktree: Path, readme_file: Path
) -> Iterator[MutatingGitWorktree]:
    with environment_as(
        GIT_DIR=str(gitdir), GIT_WORK_TREE=str(worktree), GIT_CONFIG_GLOBAL="/dev/null"
    ):
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
            [
                "git",
                "add",
                "README",
                "dir",
                "loop1",
                "loop2",
                "link-to-dir",
                "not-a-dir",
            ]
        )
        subprocess.check_call(["git", "commit", "-am", "initial commit with decode -> \x81b"])

        subprocess.check_call(["git", "tag", "first"])
        subprocess.check_call(["git", "push", "--tags", "depot", "main"])
        subprocess.check_call(["git", "branch", "--set-upstream-to", "depot/main"])

        readme_file.write_bytes("Hello World.\u2764".encode())
        subprocess.check_call(["git", "commit", "-am", "Update README."])

    with environment_as(GIT_CONFIG_GLOBAL="/dev/null"):
        yield MutatingGitWorktree(binary=GitBinary(path="git"), gitdir=gitdir, worktree=worktree)


def test_integration(worktree: Path, readme_file: Path, git: MutatingGitWorktree) -> None:
    assert set() == git.changed_files()
    assert {"README"} == git.changed_files(from_commit="HEAD^")

    assert "main" == git.branch_name

    with readme_file.open(mode="a") as fp:
        fp.write("More data.")

    (worktree / "INSTALL").write_text("make install")

    assert {"README"} == git.changed_files()
    assert {"README", "INSTALL"} == git.changed_files(include_untracked=True)

    (worktree / "WITH SPACE").write_text("space in path")
    assert {"README", "INSTALL", "WITH SPACE"} == git.changed_files(include_untracked=True)

    # Confirm that files outside of a given relative_to path are ignored
    assert set() == git.changed_files(relative_to="non-existent")


def test_integration_lines(worktree: Path, readme_file: Path, git: MutatingGitWorktree) -> None:
    files = ["README", "INSTALL", "WITH SPACE"]
    assert FrozenDict() == git.changed_files_lines(files)
    assert {
        "README": (
            Hunk(
                left=TextBlock(start=0, count=0),
                right=TextBlock(start=1, count=1),
            ),
        )
    } == git.changed_files_lines(files, from_commit="HEAD^")

    assert "main" == git.branch_name

    with readme_file.open(mode="a") as fp:
        fp.write("More data.")

    (worktree / "INSTALL").write_text("make install")

    assert FrozenDict(
        {
            "README": (
                Hunk(
                    left=TextBlock(start=1, count=1),
                    right=TextBlock(start=1, count=1),
                ),
            )
        }
    ) == git.changed_files_lines(files)

    assert {
        "README": (Hunk(left=TextBlock(start=1, count=1), right=TextBlock(start=1, count=1)),),
        "INSTALL": (Hunk(left=TextBlock(start=0, count=0), right=TextBlock(start=1, count=1)),),
    } == git.changed_files_lines(files, include_untracked=True)

    (worktree / "WITH SPACE").write_text("space in path")
    assert {
        "README": (Hunk(left=TextBlock(start=1, count=1), right=TextBlock(start=1, count=1)),),
        "INSTALL": (Hunk(left=TextBlock(start=0, count=0), right=TextBlock(start=1, count=1)),),
        "WITH SPACE": (Hunk(left=TextBlock(start=0, count=0), right=TextBlock(start=1, count=1)),),
    } == git.changed_files_lines(files, include_untracked=True)

    # Confirm that files outside of a given relative_to path are ignored
    assert FrozenDict() == git.changed_files_lines(files, relative_to="non-existent")


def test_detect_worktree(tmp_path: Path, origin: PurePath, git: MutatingGitWorktree) -> None:
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
                if expected:
                    worktree = git_worktree()
                    assert worktree and expected == worktree.worktree
                else:
                    assert git_worktree() is None

        worktree_relative_to("..", None)
        worktree_relative_to(".", clone)
        worktree_relative_to("is", clone)
        worktree_relative_to("is/a", clone)
        worktree_relative_to("is/a/dir", clone)


def test_detect_worktree_no_cwd(tmp_path: Path, origin: PurePath, git: MutatingGitWorktree) -> None:
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
            if expected:
                worktree = git_worktree(subdir=subdir)
                assert worktree and expected == worktree.worktree
            else:
                assert git_worktree(subdir=subdir) is None

        worktree_relative_to("..", None)
        worktree_relative_to(".", clone)
        worktree_relative_to("is", clone)
        worktree_relative_to("is/a", clone)
        worktree_relative_to("is/a/dir", clone)


def test_changes_in(gitdir: PurePath, worktree: Path, git: MutatingGitWorktree) -> None:
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


def test_commit_with_new_untracked_file_adds_file(worktree: Path, git: MutatingGitWorktree) -> None:
    new_file = worktree / "untracked_file"
    new_file.touch()

    assert {"untracked_file"} == git.changed_files(include_untracked=True)

    git.add(new_file)

    assert {"untracked_file"} == git.changed_files()

    git.commit("API Changes.")

    assert set() == git.changed_files(include_untracked=True)


def test_bad_ref_stderr_issues_13396(git: MutatingGitWorktree) -> None:
    with pytest.raises(
        GitBinaryException, match=re.escape("fatal: bad revision 'remote/dne...HEAD'\n")
    ):
        git.changed_files(from_commit="remote/dne")

    with pytest.raises(
        GitBinaryException,
        match=re.escape(
            "fatal: ambiguous argument 'HEAD~1000': unknown revision or path not in the working"
            + " tree.\n"
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
    assert git_worktree() is None


def test_detect_worktree_unexectuable_git(unexecutable_git: PurePath) -> None:
    assert git_worktree() is None
    assert git_worktree(binary=unexecutable_git) is None


def test_detect_worktree_invalid_executable_git(executable_git: PurePath) -> None:
    assert git_worktree() is None
    assert git_worktree(binary=executable_git) is None


def test_detect_worktree_failing_git(executable_git: Path) -> None:
    executable_git.write_text(
        dedent(
            """\
            #!/bin/sh
            exit 1
            """
        )
    )
    assert git_worktree() is None
    assert git_worktree(binary=executable_git) is None


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

    worktree = git_worktree()
    assert worktree and expected_worktree_dir == worktree.worktree
    worktree = git_worktree(binary=executable_git)
    assert worktree and expected_worktree_dir == worktree.worktree


def test_worktree_invalidation(origin: Path) -> None:
    # Confirm that requesting the worktree in two different sessions results in new instances,
    # and that the consuming `@rule` also reruns.
    with pushd(origin.as_posix()):
        init_repo("origin", origin)
        touch("BUILDROOT")

        @rule
        async def worktree_id_string() -> str:
            worktree = await Get(MaybeGitWorktree, GitWorktreeRequest())
            return str(id(worktree))

        rule_runner = RuleRunner(
            rules=[
                worktree_id_string,
                QueryRule(str, []),
            ]
        )

        rule_runner.set_options([], env_inherit={"PATH"})
        worktree_id_1 = rule_runner.request(str, [])

        rule_runner.new_session("second-session")
        rule_runner.set_options([], env_inherit={"PATH"})
        worktree_id_2 = rule_runner.request(str, [])

        assert worktree_id_1 != worktree_id_2


@pytest.mark.parametrize(
    "diff,expected",
    [
        [
            dedent(
                """\
                diff --git a/file.txt b/file.txt
                index e69de29..9daeafb 100644
                --- a/file.txt
                +++ b/file.txt
                @@ -1,0 +2 @@
                +two
                """
            ),
            {"file.txt": (Hunk(TextBlock(1, 0), TextBlock(2, 1)),)},
        ],
        [
            dedent(
                """\
                diff --git a/file.txt b/file.txt
                index e69de29..9daeafb 100644
                --- a/file.txt
                +++ b/file.txt
                @@ -2 +1,0 @@
                -two
                """
            ),
            {"file.txt": (Hunk(TextBlock(2, 1), TextBlock(1, 0)),)},
        ],
        [
            dedent(
                """\
                diff --git a/file.txt b/file.txt
                index e69de29..9daeafb 100644
                --- a/file.txt
                +++ b/file.txt
                @@ -2 +2 @@
                -two
                +four
                """
            ),
            {"file.txt": (Hunk(TextBlock(2, 1), TextBlock(2, 1)),)},
        ],
        [
            dedent(
                """\
                diff --git a/file.txt b/file.txt
                index e69de29..9daeafb 100644
                --- a/file.txt
                +++ b/file.txt
                @@ -2,2 +2,2 @@
                -two
                -three
                +five
                +six
                """
            ),
            {"file.txt": (Hunk(TextBlock(2, 2), TextBlock(2, 2)),)},
        ],
        [
            dedent(
                """\
                diff --git a/one.txt b/one.txt
                index 5626abf..d00491f 100644
                --- a/one.txt
                +++ b/one.txt
                @@ -1 +1 @@
                -one
                +1
                diff --git a/two.txt b/two.txt
                index f719efd..0cfbf08 100644
                --- a/two.txt
                +++ b/two.txt
                @@ -1 +1 @@
                -two
                +2
                """
            ),
            {
                "one.txt": (Hunk(TextBlock(1, 1), TextBlock(1, 1)),),
                "two.txt": (Hunk(TextBlock(1, 1), TextBlock(1, 1)),),
            },
        ],
        [
            dedent(
                """\
                diff --git a/sp ce.txt b/sp ce.txt
                index 9daeafb..c7e32ef 100644
                --- a/sp ce.txt
                +++ b/sp ce.txt
                @@ -1 +1 @@
                -test
                +t st
                """
            ),
            {"sp ce.txt": (Hunk(TextBlock(1, 1), TextBlock(1, 1)),)},
        ],
        [
            dedent(
                """\
                diff --git "a/q\\"ote.txt" "b/q\\"ote.txt"
                index 79fdb36..9daeafb 100644
                --- "a/q\\"ote.txt"
                +++ "b/q\\"ote.txt"
                @@ -1 +1 @@
                -te"t
                +test
                """
            ),
            {'q"ote.txt': (Hunk(TextBlock(1, 1), TextBlock(1, 1)),)},
        ],
        [
            dedent(
                """\
                diff --git a/empty b/empty
                new file mode 100644
                index 0000000000..e69de29bb2
                """
            ),
            {'empty': ()},
        ],
    ],
)
def test_parse_unified_diff(diff, expected):
    wt = DiffParser()
    actual = wt.parse_unified_diff(diff)
    assert expected == actual
