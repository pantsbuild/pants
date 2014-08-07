# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod

from twitter.common.lang import AbstractClass

from pants.base.build_environment import get_scm
from pants.scm.scm import Scm


class Workspace(AbstractClass):
  """Tracks the state of the current workspace."""

  class WorkspaceError(Exception):
    """Indicates a problem reading the local workspace."""

  @abstractmethod
  def touched_files(self, parent):
    """Returns the paths modified between the parent state and the current workspace state."""


class ScmWorkspace(Workspace):
  """A workspace that uses an Scm to determine the touched files."""

  def __init__(self, scm):
    super(ScmWorkspace, self).__init__()

    self._scm = scm or get_scm()

    if self._scm is None:
      raise self.WorkspaceError('Cannot figure out what changed without a configured '
                                'source-control system.')

  def touched_files(self, parent):
    try:
      return self._scm.changed_files(from_commit=parent, include_untracked=True)
    except Scm.ScmException as e:
      raise self.WorkspaceError("Problem detecting changed files.", e)
