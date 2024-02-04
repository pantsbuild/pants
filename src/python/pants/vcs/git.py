# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
import re
from dataclasses import dataclass
from functools import cached_property
from io import StringIO
from os import PathLike
from pathlib import Path, PurePath
from typing import Any, Iterable

from pants.core.util_rules.system_binaries import GitBinary, GitBinaryException, MaybeGitBinary
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.rules import collect_rules, rule
from pants.util.contextutil import pushd

logger = logging.getLogger(__name__)


class GitWorktree(EngineAwareReturnType):
    """Implements a safe wrapper for un-sandboxed access to Git in the user's working copy.

    This type (and any wrappers) should be marked `EngineAwareReturnType.cacheable=False`, because
    it internally uses un-sandboxed APIs, and `@rules` which produce it should re-run in each
    session. It additionally implements a default `__eq__` in order to prevent early-cutoff in the
    graph, and force any consumers of the type to re-run.
    """

    worktree: PurePath
    _gitdir: PurePath
    _git_binary: GitBinary

    def __init__(
        self,
        binary: GitBinary,
        worktree: PathLike[str] | None = None,
        gitdir: PathLike[str] | None = None,
    ) -> None:
        """Creates a git object that assumes the git repository is in the cwd by default.

        binary:    The git binary to use.
        worktree:  The path to the git repository working tree directory (typically '.').
        gitdir:    The path to the repository's git metadata directory (typically '.git').
        """
        self.worktree = Path(worktree or os.getcwd()).resolve()
        self._gitdir = Path(gitdir).resolve() if gitdir else (self.worktree / ".git")
        self._git_binary = binary

    def cacheable(self) -> bool:
        return False

    @property
    def current_rev_identifier(self):
        return "HEAD"

    @property
    def commit_id(self):
        return self._git_binary._invoke_unsandboxed(self._create_git_cmdline(["rev-parse", "HEAD"]))

    @property
    def branch_name(self) -> str | None:
        branch = self._git_binary._invoke_unsandboxed(
            self._create_git_cmdline(["rev-parse", "--abbrev-ref", "HEAD"])
        )
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
        uncommitted_changes = self._git_binary._invoke_unsandboxed(
            self._create_git_cmdline(
                ["diff", "--name-only", "HEAD"] + rel_suffix,
            )
        )

        files = set(uncommitted_changes.splitlines())
        if from_commit:
            # Grab the diff from the merge-base to HEAD using ... syntax.  This ensures we have just
            # the changes that have occurred on the current branch.
            committed_cmd = ["diff", "--name-only", from_commit + "...HEAD"] + rel_suffix
            committed_changes = self._git_binary._invoke_unsandboxed(
                self._create_git_cmdline(committed_cmd)
            )
            files.update(committed_changes.split())
        if include_untracked:
            untracked_cmd = [
                "ls-files",
                "--other",
                "--exclude-standard",
                "--full-name",
            ] + rel_suffix
            untracked = self._git_binary._invoke_unsandboxed(
                self._create_git_cmdline(untracked_cmd)
            )
            files.update(untracked.split())
        # git will report changed files relative to the worktree: re-relativize to relative_to
        return {self._fix_git_relative_path(f, relative_to) for f in files}

    def changed_file_lines(
        self,
        from_commit: str | None = None,
        relative_to: PurePath | str | None = None,
    ) -> set[str]:
        relative_to = PurePath(relative_to) if relative_to is not None else self.worktree
        rel_suffix = ["--", str(relative_to)]
        uncommitted_changes = self._git_binary._invoke_unsandboxed(
            self._create_git_cmdline(
                ["diff", "--unified=0", "HEAD"] + rel_suffix,
            )
        )

        files = set(uncommitted_changes.splitlines())
        if from_commit:
            # Grab the diff from the merge-base to HEAD using ... syntax.  This ensures we have just
            # the changes that have occurred on the current branch.
            committed_cmd = ["diff", "--unified=0", from_commit + "...HEAD"] + rel_suffix
            committed_changes = self._git_binary._invoke_unsandboxed(
                self._create_git_cmdline(committed_cmd)
            )
            files.update(committed_changes.split())

    def _parse_unified_diff(self, content: str) -> list[_Hunk]:
        buf = StringIO(content)
        hunks = []
        for line in buf:
            match = self._lines_changed_regex.match(line)
            if not match:
                continue

            g = match.groups()
            try:
                hunk = _Hunk(
                    left_start=int(g[0]),
                    left_count=int(g[2]) if g[2] is not None else 1,
                    right_start=int(g[3]),
                    right_count=int(g[5]) if g[5] is not None else 1,
                )
            except ValueError as e:
                raise ValueError(f"Failed to parse hunk: {line}") from e

            hunks.append(hunk)

        return hunks

    @cached_property
    def _lines_changed_regex(self) -> re.Pattern:
        return re.compile(r"^@@ -([0-9]+)(,([0-9]+))? \+([0-9]+)(,([0-9]+))? @@.*")

    def changes_in(self, diffspec: str, relative_to: PurePath | str | None = None) -> set[str]:
        relative_to = PurePath(relative_to) if relative_to is not None else self.worktree
        cmd = ["diff-tree", "--no-commit-id", "--name-only", "-r", diffspec]
        files = self._git_binary._invoke_unsandboxed(self._create_git_cmdline(cmd)).split()
        return {self._fix_git_relative_path(f.strip(), relative_to) for f in files}

    def _create_git_cmdline(self, args: Iterable[str]) -> list[str]:
        return [f"--git-dir={self._gitdir}", f"--work-tree={self.worktree}", *args]

    def __eq__(self, other: Any) -> bool:
        # NB: See the class doc regarding equality.
        return id(self) == id(other)


@dataclass(frozen=True)
class _Hunk:
    """Hunk of difference in unified format.

    https://www.gnu.org/software/diffutils/manual/html_node/Detailed-Unified.html
    """

    left_start: int
    left_count: int
    right_start: int
    right_count: int


@dataclass(frozen=True)
class MaybeGitWorktree(EngineAwareReturnType):
    git_worktree: GitWorktree | None = None

    def cacheable(self) -> bool:
        return False


@dataclasses.dataclass(frozen=True)
class GitWorktreeRequest:
    gitdir: PathLike[str] | None = None
    subdir: PathLike[str] | None = None


@rule
async def get_git_worktree(
    git_worktree_request: GitWorktreeRequest,
    maybe_git_binary: MaybeGitBinary,
) -> MaybeGitWorktree:
    if not maybe_git_binary.git_binary:
        return MaybeGitWorktree()

    git_binary = maybe_git_binary.git_binary
    cmd = ["rev-parse", "--show-toplevel"]

    try:
        if git_worktree_request.subdir:
            with pushd(str(git_worktree_request.subdir)):
                output = git_binary._invoke_unsandboxed(cmd)
        else:
            output = git_binary._invoke_unsandboxed(cmd)
    except GitBinaryException as e:
        logger.info(f"No git repository at {os.getcwd()}: {e!r}")
        return MaybeGitWorktree()

    git_worktree = GitWorktree(
        binary=git_binary,
        gitdir=git_worktree_request.gitdir,
        worktree=PurePath(output),
    )

    logger.debug(
        f"Detected git repository at {git_worktree.worktree} on branch {git_worktree.branch_name}"
    )
    return MaybeGitWorktree(git_worktree=git_worktree)


def rules():
    return [*collect_rules()]
