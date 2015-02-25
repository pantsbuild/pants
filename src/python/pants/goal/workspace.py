# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

from pants.base.build_environment import get_buildroot
from pants.scm.scm import Scm
from pants.util.meta import AbstractClass


class Workspace(AbstractClass):
  """Tracks the state of the current workspace."""

  class WorkspaceError(Exception):
    """Indicates a problem reading the local workspace."""

  @abstractmethod
  def touched_files(self, parent):
    """Returns the paths modified between the parent state and the current workspace state."""

  @abstractmethod
  def changes_in(self, rev_or_range):
    """Returns the paths modified by some revision, revision range or other identifier."""


class ScmWorkspace(Workspace):
  """A workspace that uses an Scm to determine the touched files."""

  def __init__(self, scm):
    super(ScmWorkspace, self).__init__()

    if scm is None:
      raise self.WorkspaceError('Cannot figure out what changed without a configured '
                                'source-control system.')
    self._scm = scm

  def touched_files(self, parent):
    try:
      return self._scm.changed_files(from_commit=parent,
                                     include_untracked=True,
                                     relative_to=get_buildroot())
    except Scm.ScmException as e:
      raise self.WorkspaceError("Problem detecting changed files.", e)

  def changes_in(self, rev_or_range):
    try:
      return self._scm.changes_in(rev_or_range, relative_to=get_buildroot())
    except Scm.ScmException as e:
      raise self.WorkspaceError("Problem detecting changes in {}.".format(rev_or_range), e)
