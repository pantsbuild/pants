# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from pathlib import Path
from typing import Optional

from pants.base.build_root import BuildRoot
from pants.scm.scm import Scm
from pants.version import VERSION as _VERSION

logger = logging.getLogger(__name__)


def pants_version() -> str:
    """Returns the pants semantic version number as a string: http://semver.org/"""
    return _VERSION


def pants_release() -> str:
    """Returns a user-friendly release label."""
    return "Pants {version} https://pypi.org/pypi/pantsbuild.pants/{version}".format(
        version=pants_version()
    )


def get_buildroot() -> str:
    """Returns the Pants build root, calculating it if needed.

    :API: public
    """
    return BuildRoot().path


def get_pants_cachedir() -> str:
    """Return the pants global cache directory."""
    # Follow the unix XDB base spec: http://standards.freedesktop.org/basedir-spec/latest/index.html.
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if not cache_home:
        cache_home = "~/.cache"
    return os.path.expanduser(os.path.join(cache_home, "pants"))


def get_pants_configdir() -> str:
    """Return the pants global config directory."""
    # Follow the unix XDB base spec: http://standards.freedesktop.org/basedir-spec/latest/index.html.
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if not config_home:
        config_home = "~/.config"
    return os.path.expanduser(os.path.join(config_home, "pants"))


def get_default_pants_config_file() -> str:
    """Return the default location of the Pants config file."""
    default_toml = Path(get_buildroot(), "pants.toml")
    if default_toml.is_file():
        return str(default_toml)
    return os.path.join(get_buildroot(), "pants.ini")


_SCM: Optional[Scm] = None


def get_scm() -> Optional[Scm]:
    """Returns the pants Scm if any.

    :API: public
    """
    # TODO(John Sirois): Extract a module/class to carry the bootstrap logic.
    global _SCM
    if _SCM:
        return _SCM
    from pants.scm.git import Git

    # We know about git, so attempt an auto-configure
    worktree = Git.detect_worktree()
    if worktree and os.path.isdir(worktree):
        git = Git(worktree=worktree)
        try:
            logger.debug(f"Detected git repository at {worktree} on branch {git.branch_name}")
            set_scm(git)
        except git.LocalException as e:
            logger.info(f"Failed to load git repository at {worktree}: {e!r}")
    return _SCM


def set_scm(scm: Optional[Scm]) -> None:
    """Sets the pants Scm."""
    if scm is None:
        return
    if not isinstance(scm, Scm):
        raise ValueError(f"The scm must be an instance of Scm, given {scm}")
    global _SCM
    _SCM = scm
