# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from enum import Enum
from pathlib import Path

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


def is_in_container() -> bool:
    """Return true if this process is likely running inside of a container."""
    # https://stackoverflow.com/a/49944991/38265 and https://github.com/containers/podman/issues/3586
    cgroup = Path("/proc/self/cgroup")
    return (
        Path("/.dockerenv").exists()
        or Path("/run/.containerenv").exists()
        or (cgroup.exists() and "docker" in cgroup.read_text("utf-8"))
    )


class _GitIinitialized(Enum):
    NO = 0


_Git: _GitIinitialized | Git | None = _GitIinitialized.NO


def get_git() -> Git | None:
    """Returns Git, if available."""
    global _Git
    if _Git is _GitIinitialized.NO:
        # We know about Git, so attempt an auto-configure
        try:
            git = Git.mount()
            logger.debug(f"Detected git repository at {git.worktree} on branch {git.branch_name}")
            _Git = git
        except GitException as e:
            logger.info(f"No git repository at {os.getcwd()}: {e!r}")
            _Git = None
    return _Git
