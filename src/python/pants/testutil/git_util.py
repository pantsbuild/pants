# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
import subprocess
from contextlib import contextmanager
from typing import Iterator, Optional

from pants.base.revision import Revision
from pants.scm.git import Git
from pants.util.contextutil import environment_as, temporary_dir

MIN_REQUIRED_GIT_VERSION = Revision.semver("1.7.10")


def git_version() -> Revision:
    """Get a Version() based on installed command-line git's version."""
    stdout = subprocess.run(
        ["git", "--version"], stdout=subprocess.PIPE, encoding="utf-8", check=True
    ).stdout
    # stdout is like 'git version 1.9.1.598.g9119e8b\n'  We want '1.9.1.598'
    matches = re.search(r"\s(\d+(?:\.\d+)*)[\s\.]", stdout)
    if matches is None:
        raise ValueError(f"Not able to parse git version from {stdout}.")
    return Revision.lenient(matches.group(1))


@contextmanager
def initialize_repo(worktree: str, *, gitdir: Optional[str] = None) -> Iterator[Git]:
    """Initialize a git repository for the given `worktree`.

    NB: The given `worktree` must contain at least one file which will be committed to form an initial
    commit.

    :param worktree: The path to the git work tree.
    :param gitdir: An optional path to the `.git` dir to use.
    :returns: A `Git` repository object that can be used to interact with the repo.
    """

    @contextmanager
    def use_gitdir() -> Iterator[str]:
        if gitdir:
            yield gitdir
        else:
            with temporary_dir() as d:
                yield d

    with use_gitdir() as git_dir, environment_as(GIT_DIR=git_dir, GIT_WORK_TREE=worktree):
        subprocess.run(["git", "init"], check=True)
        subprocess.run(["git", "config", "user.email", "you@example.com"], check=True)
        # TODO: This method inherits the global git settings, so if a developer has gpg signing on, this
        # will turn that off. We should probably just disable reading from the global config somehow:
        # https://git-scm.com/docs/git-config.
        subprocess.run(["git", "config", "commit.gpgSign", "false"], check=True)
        subprocess.run(["git", "config", "user.name", "Your Name"], check=True)
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-am", "Add project files."], check=True)
        yield Git(gitdir=git_dir, worktree=worktree)
