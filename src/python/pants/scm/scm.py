# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod


class Scm(ABC):
    """Abstracts high-level scm operations needed by pants core and pants tasks.

    :API: public
    """

    class ScmException(Exception):
        """Indicates a problem interacting with the scm.

        :API: public
        """

    class LocalException(ScmException):
        """Indicates a problem performing a local scm operation.

        :API: public
        """

    @property
    @abstractmethod
    def current_rev_identifier(self) -> str:
        """Identifier for the tip/head of the current branch eg. "HEAD" in git.

        :API: public
        """

    @property
    @abstractmethod
    def commit_id(self) -> str:
        """Returns the id of the current commit.

        :API: public
        """

    @property
    @abstractmethod
    def branch_name(self) -> str:
        """Returns the name of the current branch if any.

        :API: public
        """

    @property
    @abstractmethod
    def worktree(self):
        """Returns the worktree for the SCM.

        :API: public
        """

    @abstractmethod
    def changed_files(self, from_commit=None, include_untracked=False, relative_to=None):
        """Returns a list of files with uncommitted changes or else files changed since from_commit.

        If include_untracked=True then any workspace files that are un-tracked by the scm and not
        ignored will be included as well.

        If relative_to is None, then the paths will be relative to the working tree of the SCM
        implementation (which might NOT match the buildroot).

        :API: public
        """

    @abstractmethod
    def changes_in(self, diffspec, relative_to=None):
        """Returns a list of files changed by some diffspec (eg sha, range, ref, etc)

        :API: public

        :param str diffspec: Some diffspec meaningful to the SCM.
        :param str relative_to: a path to which results should be relative (instead of SCM root)
        """

    @abstractmethod
    def commit(self, message, verify=True):
        """Commits all the changes for tracked files in the local workspace.

        Subclasses should raise LocalException if there is a problem making the commit.

        :API: public
        """

    @abstractmethod
    def add(self, *paths):
        """Add paths to the set of tracked files.

        Subclasses should raise LocalException if there is a problem adding the paths.

        :API: public
        """
