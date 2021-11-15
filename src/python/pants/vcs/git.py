# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from os import PathLike
from pathlib import Path, PurePath
from typing import Iterable

from pants.util.contextutil import pushd
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


class GitException(Exception):
    pass


@frozen_after_init
@dataclass(unsafe_hash=True)
class Git:
    worktree: PurePath
    _gitdir: PurePath
    _gitcmd: str

    def __init__(
        self,
        worktree: PathLike[str] | None = None,
        *,
        gitdir: PathLike[str] | None = None,
        binary: str = "git",
    ) -> None:
        """Creates a git object that assumes the git repository is in the cwd by default.

        worktree:  The path to the git repository working tree directory (typically '.').
        gitdir:    The path to the repository's git metadata directory (typically '.git').
        binary:    The path to the git binary to use, 'git' by default.
        """
        self.worktree = Path(worktree or os.getcwd()).resolve()
        self._gitdir = Path(gitdir).resolve() if gitdir else (self.worktree / ".git")
        self._gitcmd = binary

    @classmethod
    def mount(cls, subdir: str | PurePath | None = None, *, binary: str | PurePath = "git") -> Git:
        """Detect the git working tree above cwd and return it.

        :param string subdir: The path to start searching for a git repo.
        :param string binary: The path to the git binary to use, 'git' by default.
        :returns: a Git object that is configured to operate on the found git repo.
        :raises: :class:`GitException` if no git repo could be found.
        """
        cmd = [str(binary), "rev-parse", "--show-toplevel"]
        if subdir:
            with pushd(str(subdir)):
                process, out, err = cls._invoke(cmd)
        else:
            process, out, err = cls._invoke(cmd)
        cls._check_result(cmd, process.returncode, err.decode())
        return cls(worktree=PurePath(cls._cleanse(out)))

    @staticmethod
    def _invoke(cmd: list[str]) -> tuple[subprocess.Popen, bytes, bytes]:
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            # Binary DNE or is not executable
            cmd_str = " ".join(cmd)
            raise GitException(f"Failed to execute command {cmd_str}: {e!r}")
        out, err = process.communicate()
        return process, out, err

    @classmethod
    def _cleanse(cls, output: bytes) -> str:
        return output.decode().strip()

    @classmethod
    def _check_result(cls, cmd: Iterable[str], result: int, failure_msg: str | None = None) -> None:
        if result != 0:
            cmd_str = " ".join(cmd)
            raise GitException(failure_msg or f"{cmd_str} failed with exit code {result}")

    @property
    def current_rev_identifier(self):
        return "HEAD"

    @property
    def commit_id(self):
        return self._check_output(["rev-parse", "HEAD"])

    @property
    def branch_name(self) -> str | None:
        branch = self._check_output(["rev-parse", "--abbrev-ref", "HEAD"])
        return None if branch == "HEAD" else branch

    def _fix_git_relative_path(self, worktree_path: str, relative_to: PurePath | str) -> str:
        return str((self.worktree / worktree_path).relative_to(relative_to))

    def changed_files(
        self,
        from_commit: str | None = None,
        include_untracked: bool = False,
        relative_to: PurePath | str | None = None,
    ) -> set[str]:
        relative_to = PurePath(relative_to) if relative_to is not None else self.worktree
        rel_suffix = ["--", str(relative_to)]
        uncommitted_changes = self._check_output(["diff", "--name-only", "HEAD"] + rel_suffix)

        files = set(uncommitted_changes.splitlines())
        if from_commit:
            # Grab the diff from the merge-base to HEAD using ... syntax.  This ensures we have just
            # the changes that have occurred on the current branch.
            committed_cmd = ["diff", "--name-only", from_commit + "...HEAD"] + rel_suffix
            committed_changes = self._check_output(committed_cmd)
            files.update(committed_changes.split())
        if include_untracked:
            untracked_cmd = [
                "ls-files",
                "--other",
                "--exclude-standard",
                "--full-name",
            ] + rel_suffix
            untracked = self._check_output(untracked_cmd)
            files.update(untracked.split())
        # git will report changed files relative to the worktree: re-relativize to relative_to
        return {self._fix_git_relative_path(f, relative_to) for f in files}

    def changes_in(self, diffspec: str, relative_to: PurePath | str | None = None) -> set[str]:
        relative_to = PurePath(relative_to) if relative_to is not None else self.worktree
        cmd = ["diff-tree", "--no-commit-id", "--name-only", "-r", diffspec]
        files = self._check_output(cmd).split()
        return {self._fix_git_relative_path(f.strip(), relative_to) for f in files}

    # N.B.: Only used by tests.
    def commit(self, message: str) -> None:
        self._check_call(["commit", "--all", "--message", message])

    # N.B.: Only used by tests.
    def add(self, *paths: PurePath) -> None:
        self._check_call(["add", *(str(path) for path in paths)])

    def _check_call(self, args: Iterable[str]) -> None:
        cmd = self._create_git_cmdline(args)
        self._log_call(cmd)
        result = subprocess.call(cmd)
        self._check_result(cmd, result)

    def _check_output(self, args: Iterable[str]) -> str:
        cmd = self._create_git_cmdline(args)
        self._log_call(cmd)

        process, out, err = self._invoke(cmd)

        self._check_result(cmd, process.returncode, err.decode())
        return self._cleanse(out)

    def _create_git_cmdline(self, args: Iterable[str]) -> list[str]:
        return [self._gitcmd, f"--git-dir={self._gitdir}", f"--work-tree={self.worktree}", *args]

    def _log_call(self, cmd: Iterable[str]) -> None:
        logger.debug("Executing: " + " ".join(cmd))
