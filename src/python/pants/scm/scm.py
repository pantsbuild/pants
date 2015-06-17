# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod, abstractproperty

from pants.util.meta import AbstractClass


class Scm(AbstractClass):
  """Abstracts high-level scm operations needed by pants core and pants tasks."""

  class ScmException(Exception):
    """Indicates a problem interacting with the scm."""

  class RemoteException(ScmException):
    """Indicates a problem performing a remote scm operation."""

  class LocalException(ScmException):
    """Indicates a problem performing a local scm operation."""

  @abstractproperty
  def current_rev_identifier(self):
    """Identifier for the tip/head of the current branch eg. "HEAD" in git"""

  @abstractproperty
  def commit_id(self):
    """Returns the id of the current commit."""

  @abstractproperty
  def server_url(self):
    """Returns the url of the (default) remote server."""

  @abstractproperty
  def tag_name(self):
    """Returns the name of the current tag if any."""

  @abstractproperty
  def branch_name(self):
    """Returns the name of the current branch if any."""

  @abstractmethod
  def commit_date(self, commit_reference):
    """Returns the commit date of the referenced commit."""

  @abstractmethod
  def changed_files(self, from_commit=None, include_untracked=False, relative_to=None):
    """Returns a list of files with uncommitted changes or else files changed since from_commit.

    If include_untracked=True then any workspace files that are un-tracked by the scm and not
    ignored will be included as well.

    If relative_to is None, then the paths will be relative to the working tree of the SCM
    implementation (which might NOT match the buildroot.)
    """

  @abstractmethod
  def changes_in(self, diffspec, relative_to=None):
    """Returns a list of files changed by some diffspec (eg sha, range, ref, etc)

    :param str diffspec: Some diffspec meaningful to the SCM.
    :param str relative_to: a path to which results should be relative (instead of SCM root)
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
    """Commits all the changes for tracked files in the local workspace.

    Subclasses should raise LocalException if there is a problem making the commit.
    """

  @abstractmethod
  def add(self, *paths):
    """Add paths to the set of tracked files.

    Subclasses should raise LocalException if there is a problem adding the paths.
    """

  @abstractmethod
  def push(self):
    """Push the current branch of the local repository to the corresponding local branch
    on the server

    Subclasses should raise RemoteException if there is a problem getting the commit to the
    server.
    """
