# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import sys

from pants.base.build_root import BuildRoot
from pants.scm.scm import Scm
from pants.version import VERSION as _VERSION


logger = logging.getLogger(__name__)


def pants_version():
  """Returns the pants semantic version number: http://semver.org/"""
  return _VERSION


def pants_release():
  """Returns a user-friendly release label."""
  return ('Pants {version} https://pypi.python.org/pypi/pantsbuild.pants/{version}'
          .format(version=pants_version()))


def get_buildroot():
  """Returns the pants build root, calculating it if needed."""
  try:
    return BuildRoot().path
  except BuildRoot.NotFoundError as e:
    print(e.message, file=sys.stderr)
    sys.exit(1)


def get_pants_cachedir():
  """Return the pants global cache directory."""
  # Follow the unix XDB base spec: http://standards.freedesktop.org/basedir-spec/latest/index.html.
  cache_home = os.environ.get('XDG_CACHE_HOME')
  if not cache_home:
    cache_home = '~/.cache'
  return os.path.expanduser(os.path.join(cache_home, 'pants'))


def get_pants_configdir():
  """Return the pants global config directory."""
  # Follow the unix XDB base spec: http://standards.freedesktop.org/basedir-spec/latest/index.html.
  config_home = os.environ.get('XDG_CONFIG_HOME')
  if not config_home:
    config_home = '~/.config'
  return os.path.expanduser(os.path.join(config_home, 'pants'))


_SCM = None


def get_scm():
  """Returns the pants Scm if any."""
  # TODO(John Sirois): Extract a module/class to carry the bootstrap logic.
  global _SCM
  if not _SCM:
    from pants.scm.git import Git
    # We know about git, so attempt an auto-configure
    worktree = Git.detect_worktree()
    if worktree and os.path.isdir(worktree):
      git = Git(worktree=worktree)
      try:
        logger.info('Detected git repository at {} on branch {}'.format(worktree, git.branch_name))
        set_scm(git)
      except git.LocalException as e:
        logger.info('Failed to load git repository at {}: {}'.format(worktree, e))
  return _SCM


def set_scm(scm):
  """Sets the pants Scm."""
  if scm is not None:
    if not isinstance(scm, Scm):
      raise ValueError('The scm must be an instance of Scm, given {}'.format(scm))
    global _SCM
    _SCM = scm
