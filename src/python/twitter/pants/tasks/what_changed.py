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

import os
import sys

from abc import abstractmethod
from collections import defaultdict

from twitter.common.lang import AbstractClass

from twitter.pants import TaskError
from twitter.pants.base.build_environment import get_buildroot, get_scm
from twitter.pants.base.build_file import BuildFile
from twitter.pants.base.target import Target
from twitter.pants.scm import Scm
from twitter.pants.tasks.console_task import ConsoleTask


class WhatChanged(ConsoleTask):
  """Emits the targets that have been modified since a given commit."""

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(WhatChanged, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('parent'), dest='what_changed_create_prefix', default='HEAD',
                            help='[%default] Identifies the parent tree-ish to calculate changes '
                                 'against.')

    option_group.add_option(mkflag("files"), mkflag("files", negate=True), default=False,
                            action="callback", callback=mkflag.set_bool,
                            dest='what_changed_show_files',
                            help='[%default] Shows changed files instead of the targets that own '
                                 'them.')

  def __init__(self, context, workspace, outstream=sys.stdout):
    if not isinstance(workspace, Workspace):
      raise ValueError('WhatChanged requires a Workspace, given %s' % workspace)

    super(WhatChanged, self).__init__(context, outstream)

    self._workspace = workspace

    self._parent = context.options.what_changed_create_prefix
    self._show_files = context.options.what_changed_show_files

    self._filemap = defaultdict(set)

  def console_output(self, _):
    touched_files = self._get_touched_files()
    if self._show_files:
      for file in touched_files:
        yield file
    else:
      touched_targets = set()
      for file in touched_files:
        for touched_target in self._owning_targets(file):
          if touched_target not in touched_targets:
            touched_targets.add(touched_target)
            yield str(touched_target.address)

  def _get_touched_files(self):
    try:
      return self._workspace.touched_files(self._parent)
    except Workspace.WorkspaceError as e:
      raise TaskError(e)

  def _owning_targets(self, file):
    for build_file in self._candidate_owners(file):
      is_build_file = (build_file.full_path == os.path.join(get_buildroot(), file))
      for address in Target.get_all_addresses(build_file):
        target = Target.get(address)
        if target and (is_build_file or (target.has_sources() and self._owns(target, file))):
          yield target

  def _candidate_owners(self, file):
    build_file = BuildFile(get_buildroot(), relpath=os.path.dirname(file), must_exist=False)
    if build_file.exists():
      yield build_file
    for sibling in build_file.siblings():
      yield sibling
    for ancestor in build_file.ancestors():
      yield ancestor

  def _owns(self, target, file):
    if target not in self._filemap:
      files = self._filemap[target]
      for owned_file in target.sources:
        owned_path = os.path.join(target.target_base, owned_file)
        files.add(owned_path)
    return file in self._filemap[target]


class Workspace(AbstractClass):
  """Tracks the state of the current workspace."""

  class WorkspaceError(Exception):
    """Indicates a problem reading the local workspace."""

  @abstractmethod
  def touched_files(self, parent):
    """Returns the set of paths modified between the given parent commit and the current local
    workspace state.
    """


class ScmWorkspace(Workspace):
  """A workspace that uses an Scm to determine the touched files."""

  def __init__(self, scm):
    super(ScmWorkspace, self).__init__()

    self._scm = scm or get_scm()

    if self._scm is None:
      raise self.WorkspaceError('Cannot figure out what changed without a configured source-control system.')

  def touched_files(self, parent):
    try:
      return self._scm.changed_files(from_commit=parent, include_untracked=True)
    except Scm.ScmException as e:
      raise self.WorkspaceError("Problem detecting changed files.", e)


class ScmWhatChanged(WhatChanged):
  def __init__(self, context, scm=None, outstream=sys.stdout):
    """Creates a WhatChanged task that uses an Scm to determine changed files.

    context:    The pants execution context.
    scm:        The scm to use, taken from the globally configured scm if None.
    outstream:  The stream to write changed files or targets to.
    """
    super(ScmWhatChanged, self).__init__(context, ScmWorkspace(scm or get_scm()), outstream)
