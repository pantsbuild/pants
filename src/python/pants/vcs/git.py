# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
from io import StringIO
from os import PathLike
from pathlib import Path, PurePath
from typing import Any, DefaultDict, Iterable

from pants.core.util_rules.system_binaries import GitBinary, GitBinaryException, MaybeGitBinary
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.rules import collect_rules, rule
from pants.util.contextutil import pushd
from pants.vcs.hunk import Hunk, TextBlock

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
        self._diff_parser = DiffParser()

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
            committed_cmd = [
                "diff",
                "--name-only",
                from_commit + "...HEAD",
            ] + rel_suffix
            committed_changes = self._git_binary._invoke_unsandboxed(
                self._create_git_cmdline(committed_cmd)
            )
            files.update(committed_changes.splitlines())
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
            files.update(untracked.splitlines())
        # git will report changed files relative to the worktree: re-relativize to relative_to
        return {self._fix_git_relative_path(f, relative_to) for f in files}

    def changed_files_lines(
        self,
        paths: Iterable[str],
        /,
        *,
        from_commit: str | None = None,
        relative_to: PurePath | str | None = None,
        include_untracked: bool = False,
    ) -> dict[str, tuple[Hunk, ...]]:
        relative_to = PurePath(relative_to) if relative_to is not None else self.worktree

        result = self._git_diff(
            "--unified=0",
            "HEAD",
            "--",
            *[str(relative_to / path) for path in paths],
        )

        if from_commit:
            diff = self._git_diff(
                "--unified=0",
                from_commit + "...HEAD",
                "--",
                *[str(relative_to / path) for path in paths],
            )
            result.update(diff)

        if include_untracked:
            # There is no git diff flag to include untracked files, so we get
            # the list of untracked files and manually create the diff by
            # comparing each file to an empty /dev/null.
            untracked_files = self._git(
                "ls-files",
                "--other",
                "--exclude-standard",
                "--full-name",
            ).splitlines()
            for file in set(untracked_files).intersection(paths):
                untracked_diff = self._git_diff("--no-index", "/dev/null", str(relative_to / file))
                assert len(untracked_diff) == 1
                result[file] = next(iter(untracked_diff.values()))

        return result

    def _git(self, *args: str) -> str:
        """Run unsandboxed git command."""
        return self._git_binary._invoke_unsandboxed(self._create_git_cmdline(args))

    def _git_diff(self, *args: str) -> dict[str, tuple[Hunk, ...]]:
        """Run unsandboxed git diff command and parse the diff."""
        return self._diff_parser.parse_unified_diff(self._git("diff", *args))

    def changes_in(self, diffspec: str, relative_to: PurePath | str | None = None) -> set[str]:
        relative_to = PurePath(relative_to) if relative_to is not None else self.worktree
        cmd = ["diff-tree", "--no-commit-id", "--name-only", "-r", diffspec]
        files = self._git_binary._invoke_unsandboxed(self._create_git_cmdline(cmd)).splitlines()
        return {self._fix_git_relative_path(f.strip(), relative_to) for f in files}

    def _create_git_cmdline(self, args: Iterable[str]) -> list[str]:
        return [f"--git-dir={self._gitdir}", f"--work-tree={self.worktree}", *args]

    def __eq__(self, other: Any) -> bool:
        # NB: See the class doc regarding equality.
        return id(self) == id(other)


class ParseError(Exception):
    pass


class DiffParser:
    def parse_unified_diff(self, content: str) -> dict[str, tuple[Hunk, ...]]:
        buf = StringIO(content)
        current_file = None
        hunks: DefaultDict[str, list[Hunk]] = defaultdict(list)
        for line in buf:
            line = line.strip()

            if match := self._filename_regex.match(line):
                if current_file is not None:
                    hunks.setdefault(
                        current_file, [Hunk(left=None, right=TextBlock(start=0, count=0))]
                    )
                current_file = self._parse_filename(match)
                if current_file is None:
                    raise ValueError(f"failed to parse filename from line: `{line}`")
                continue

            if match := self._lines_changed_regex.match(line):
                if current_file is None:
                    raise ParseError(f"missing filename in the diff:\n{content}")

                try:
                    hunk = self._parse_hunk(match, line)
                except ValueError as e:
                    raise ValueError(f"Failed to parse hunk: {line}") from e

                hunks[current_file].append(hunk)
                continue

        if current_file is not None:
            hunks.setdefault(current_file, [Hunk(left=None, right=TextBlock(start=0, count=0))])
        return {filename: tuple(file_hunks) for filename, file_hunks in hunks.items()}

    @cached_property
    def _lines_changed_regex(self) -> re.Pattern:
        return re.compile(r"^@@ -([0-9]+)(,([0-9]+))? \+([0-9]+)(,([0-9]+))? @@.*")

    def _parse_hunk(self, match: re.Match, line: str) -> Hunk:
        g = match.groups()
        return Hunk(
            left=TextBlock(
                start=int(g[0]),
                count=int(g[2]) if g[2] is not None else 1,
            ),
            right=TextBlock(
                start=int(g[3]),
                count=int(g[5]) if g[5] is not None else 1,
            ),
        )

    @cached_property
    def _filename_regex(self) -> re.Pattern:
        # This only handles whitespaces. It doesn't work if a filename has something weird
        # in it that needs escaping, e.g. a double quote.
        a_file = r'(?:a/(?:[^"]+)|"a/(:?(?:[^"]|\\")+)")'
        b_file = r'(?:b/(?P<unquoted>[^"]+)|"b/(?P<quoted>(?:[^"]|\\")+)")'
        return re.compile(rf"^diff --git {a_file} {b_file}$")

    def _parse_filename(self, match: re.Match) -> str | None:
        unquoted = str(g) if (g := match.group("unquoted")) is not None else None
        quoted = str(g).replace(r"\"", '"') if (g := match.group("quoted")) is not None else None
        return unquoted or quoted


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
