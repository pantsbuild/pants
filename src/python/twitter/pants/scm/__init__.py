# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

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
