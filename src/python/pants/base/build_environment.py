# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from typing import Optional

from pants.base.build_root import BuildRoot
from pants.engine.internals import native_engine
from pants.vcs.git import Git, GitException
from pants.version import VERSION

logger = logging.getLogger(__name__)


def pants_version() -> str:
    """Returns the pants semantic version number as a string: http://semver.org/"""
    return VERSION


def get_buildroot() -> str:
    """Returns the Pants build root, calculating it if needed.

    :API: public
    """
    return BuildRoot().path


def get_pants_cachedir() -> str:
    """Return the Pants global cache directory."""
    return native_engine.default_cache_path()


def get_default_pants_config_file() -> str:
    """Return the default location of the Pants config file."""
    return os.path.join(get_buildroot(), "pants.toml")


_Git: Optional[Git] = None


def get_git() -> Optional[Git]:
    """Returns Git, if available."""
    global _Git
    if _Git:
        return _Git

    # We know about Git, so attempt an auto-configure
    worktree = Git.detect_worktree()
    if worktree and os.path.isdir(worktree):
        git = Git(worktree=worktree)
        try:
            logger.debug(f"Detected git repository at {worktree} on branch {git.branch_name}")
            _Git = git
        except GitException as e:
            logger.info(f"Failed to load git repository at {worktree}: {e!r}")
    return _Git
