# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

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
  """Returns the pants ROOT_DIR, calculating it if needed."""
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
    # We know about git, so attempt an auto-configure
    git_dir = os.path.join(get_buildroot(), '.git')
    if os.path.isdir(git_dir):
      from pants.scm.git import Git
      git = Git(worktree=get_buildroot())
      try:
        log.info('Detected git repository on branch %s' % git.branch_name)
        set_scm(git)
      except git.LocalException:
        pass
  return _SCM


def set_scm(scm):
  """Sets the pants Scm."""
  if scm is not None:
    if not isinstance(scm, Scm):
      raise ValueError('The scm must be an instance of Scm, given %s' % scm)
    global _SCM
    _SCM = scm
