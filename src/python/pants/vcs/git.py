# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import subprocess

from pants.util.contextutil import pushd

# 40 is Linux's hard-coded limit for total symlinks followed when resolving a path.
MAX_SYMLINKS_IN_REALPATH = 40
GIT_HASH_LENGTH = 20

NUL = b"\0"
SPACE = b" "
NEWLINE = b"\n"
EMPTY_STRING = b""


logger = logging.getLogger(__name__)


class GitException(Exception):
    pass


class Git:
    @classmethod
    def detect_worktree(cls, binary="git", subdir=None):
        """Detect the git working tree above cwd and return it; else, return None.

        :param string binary: The path to the git binary to use, 'git' by default.
        :param string subdir: The path to start searching for a git repo.
        :returns: path to the directory where the git working tree is rooted.
        :rtype: string
        """
        # TODO(John Sirois): This is only used as a factory for a Git instance in
        # pants.base.build_environment.get_scm, encapsulate in a true factory method.
        cmd = [binary, "rev-parse", "--show-toplevel"]
        try:
            if subdir:
                with pushd(subdir):
                    process, out = cls._invoke(cmd, stderr=subprocess.DEVNULL)
            else:
                process, out = cls._invoke(cmd, stderr=subprocess.DEVNULL)
            cls._check_result(cmd, process.returncode)
        except GitException:
            return None
        return cls._cleanse(out)

    @classmethod
    def _invoke(cls, cmd, stderr=None):
        """Invoke the given command, and return a tuple of process and raw binary output.

        If stderr is defined as None, it will flow to wherever it is currently mapped
        for the parent process, generally to the terminal where the user can see the error
        (cf. https://docs.python.org/3.7/library/subprocess.html#subprocess.Popen ). In
        some cases we want to treat it specially, which is why it is exposed
        in the signature of _invoke.

        :param list cmd: The command in the form of a list of strings
        :returns: The completed process object and its standard output.
        :raises: Scm.LocalException if there was a problem exec'ing the command at all.
        """
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=stderr)
        except OSError as e:
            # Binary DNE or is not executable
            cmd_str = " ".join(cmd)
            raise GitException(f"Failed to execute command {cmd_str}: {e!r}")
        out, _ = process.communicate()
        return process, out

    @classmethod
    def _cleanse(cls, output, errors="strict"):
        return output.strip().decode("utf-8", errors=errors)

    @classmethod
    def _check_result(cls, cmd, result, failure_msg=None):
        if result != 0:
            cmd_str = " ".join(cmd)
            raise GitException(failure_msg or f"{cmd_str} failed with exit code {result}")

    def __init__(self, binary="git", gitdir=None, worktree=None, remote=None, branch=None):
        """Creates a git scm proxy that assumes the git repository is in the cwd by default.

        binary:    The path to the git binary to use, 'git' by default.
        gitdir:    The path to the repository's git metadata directory (typically '.git').
        worktree:  The path to the git repository working tree directory (typically '.').
        remote:    The default remote to use.
        branch:    The default remote branch to use.
        """
        super().__init__()
        self._gitcmd = binary
        self._worktree = os.path.realpath(worktree or os.getcwd())
        self._gitdir = os.path.realpath(gitdir) if gitdir else os.path.join(self._worktree, ".git")
        self._remote = remote
        self._branch = branch

    @property
    def current_rev_identifier(self):
        return "HEAD"

    @property
    def worktree(self):
        return self._worktree

    @property
    def commit_id(self):
        return self._check_output(["rev-parse", "HEAD"])

    @property
    def branch_name(self):
        branch = self._check_output(["rev-parse", "--abbrev-ref", "HEAD"])
        return None if branch == "HEAD" else branch

    def fix_git_relative_path(self, worktree_path, relative_to):
        return os.path.relpath(os.path.join(self._worktree, worktree_path), relative_to)

    def changed_files(self, from_commit=None, include_untracked=False, relative_to=None):
        relative_to = relative_to or self._worktree
        rel_suffix = ["--", relative_to]
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
        return {self.fix_git_relative_path(f, relative_to) for f in files}

    def changes_in(self, diffspec, relative_to=None):
        relative_to = relative_to or self._worktree
        cmd = ["diff-tree", "--no-commit-id", "--name-only", "-r", diffspec]
        files = self._check_output(cmd).split()
        return {self.fix_git_relative_path(f.strip(), relative_to) for f in files}

    def commit(self, message, verify=True):
        cmd = ["commit", "--all", "--message=" + message]
        if not verify:
            cmd.append("--no-verify")
        self._check_call(cmd)

    def add(self, *paths):
        self._check_call(["add"] + list(paths))

    def _check_call(self, args, failure_msg=None):
        cmd = self._create_git_cmdline(args)
        self._log_call(cmd)
        result = subprocess.call(cmd)
        self._check_result(cmd, result, failure_msg)

    def _check_output(self, args, failure_msg=None, errors="strict"):
        cmd = self._create_git_cmdline(args)
        self._log_call(cmd)

        process, out = self._invoke(cmd)

        self._check_result(cmd, process.returncode, failure_msg)
        return self._cleanse(out, errors=errors)

    def _create_git_cmdline(self, args):
        return [self._gitcmd, "--git-dir=" + self._gitdir, "--work-tree=" + self._worktree] + args

    def _log_call(self, cmd):
        logger.debug("Executing: " + " ".join(cmd))
