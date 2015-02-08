# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys

from twitter.common import log

from pants.base.build_root import BuildRoot
from pants.scm.scm import Scm
from pants.version import VERSION as _VERSION


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
        log.info('Detected git repository at %s on branch %s' % (worktree, git.branch_name))
        set_scm(git)
      except git.LocalException as e:
        log.info('Failed to load git repository at %s: %s' % (worktree, e))
  return _SCM


def set_scm(scm):
  """Sets the pants Scm."""
  if scm is not None:
    if not isinstance(scm, Scm):
      raise ValueError('The scm must be an instance of Scm, given %s' % scm)
    global _SCM
    _SCM = scm
