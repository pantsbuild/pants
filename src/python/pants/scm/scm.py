# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod, abstractproperty

from twitter.common.lang import AbstractClass


class Scm(AbstractClass):
  """Abstracts high-level scm operations needed by pants core and pants tasks."""

  class ScmException(Exception):
    """Indicates a problem interacting with the scm."""

  class RemoteException(ScmException):
    """Indicates a problem performing a remote scm operation."""

  class LocalException(ScmException):
    """Indicates a problem performing a local scm operation."""

  @abstractproperty
  def commit_id(self):
    """Returns the id of the current commit."""

  @abstractproperty
  def tag_name(self):
    """Returns the name of the current tag if any."""

  @abstractproperty
  def branch_name(self):
    """Returns the name of the current branch if any."""

  @abstractmethod
  def changed_files(self, from_commit=None, include_untracked=False):
    """Returns a list of files with uncommitted changes or else files changed since from_commit.

    If include_untracked=True then any workspace files that are un-tracked by the scm and not
    ignored will be included as well.
    """

  @abstractmethod
  def changelog(self, from_commit=None, files=None):
    """Produces a changelog from the given commit or the 1st commit if none is specified until the
    present workspace commit for the changes affecting the given files.

    If no files are given then the full change log should be produced.
    """

  @abstractmethod
  def refresh(self):
    """Refreshes the local workspace with any changes on the server.

    Subclasses should raise some form of ScmException to indicate a refresh error whether it be
    a conflict or a communication channel error.
    """

  @abstractmethod
  def tag(self, name, message=None):
    """Tags the state in the local workspace and ensures this tag is on the server.

    Subclasses should raise RemoteException if there is a problem getting the tag to the server.
    """

  @abstractmethod
  def commit(self, message):
    """Commits the changes in the local workspace and ensure this commit is on the server.

    Subclasses should raise RemoteException if there is a problem getting the tag to the server.
    """
