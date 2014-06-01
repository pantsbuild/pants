# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod
import os
import sys

from twitter.common.lang import AbstractClass

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.build_environment import get_buildroot, get_scm
from pants.base.build_file import BuildFile
from pants.base.exceptions import TaskError
from pants.scm import Scm


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

  def __init__(self, context, workdir, workspace, outstream=sys.stdout):
    super(WhatChanged, self).__init__(context, workdir, outstream)

    if not isinstance(workspace, Workspace):
      raise ValueError('WhatChanged requires a Workspace, given %s' % workspace)

    self._workspace = workspace

    self._parent = context.options.what_changed_create_prefix
    self._show_files = context.options.what_changed_show_files

    self._filemap = {}

  def console_output(self, _):
    touched_files = self._get_touched_files()
    if self._show_files:
      for path in touched_files:
        yield path
    else:
      touched_targets = set()
      for path in touched_files:
        for touched_target in self._owning_targets(path):
          if touched_target not in touched_targets:
            touched_targets.add(touched_target)
            yield touched_target.address.build_file_spec

  def _get_touched_files(self):
    try:
      return self._workspace.touched_files(self._parent)
    except Workspace.WorkspaceError as e:
      raise TaskError(e)

  def _owning_targets(self, path):
    for build_file in self._candidate_owners(path):
      build_graph = self.context.build_graph
      build_file_parser = self.context.build_file_parser
      build_file_parser.parse_build_file(build_file)
      for address in build_file_parser.addresses_by_build_file[build_file]:
        build_file_parser.inject_spec_closure_into_build_graph(address.spec, build_graph)
      is_build_file = (build_file.full_path == os.path.join(get_buildroot(), path))

      for target in build_graph.sorted_targets():
        # HACK: Python targets currently wrap old-style file resources in a synthetic
        # resources target, but they do so lazily, when target.resources is first accessed.
        # We force that access here, so that the targets will show up in the subsequent
        # invocation of build_graph.sorted_targets().
        if target.has_resources:
          _ = target.resources
      for target in build_graph.sorted_targets():
        if (is_build_file and not target.is_synthetic and
            target.address.build_file == build_file) or self._owns(target, path):
          # We call concrete_derived_from because of the python target resources hack
          # mentioned above; It's really the original target that owns the resource files.
          yield target.concrete_derived_from

  def _candidate_owners(self, path):
    build_file = BuildFile(get_buildroot(), relpath=os.path.dirname(path), must_exist=False)
    if build_file.exists():
      yield build_file
    for sibling in build_file.siblings():
      yield sibling
    for ancestor in build_file.ancestors():
      yield ancestor

  def _owns(self, target, path):
    if target not in self._filemap:
      self._filemap[target] = set(target.sources_relative_to_buildroot())
    return path in self._filemap[target]


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
      raise self.WorkspaceError('Cannot figure out what changed without a configured '
                                'source-control system.')

  def touched_files(self, parent):
    try:
      return self._scm.changed_files(from_commit=parent, include_untracked=True)
    except Scm.ScmException as e:
      raise self.WorkspaceError("Problem detecting changed files.", e)


class ScmWhatChanged(WhatChanged):
  def __init__(self, context, workdir, scm=None, outstream=sys.stdout):
    """Creates a WhatChanged task that uses an Scm to determine changed files.

    context:    The pants execution context.
    workdir:    The directory to work in.
    scm:        The scm to use, taken from the globally configured scm if None.
    outstream:  The stream to write changed files or targets to.
    """
    super(ScmWhatChanged, self).__init__(context, workdir, ScmWorkspace(scm or get_scm()),
                                         outstream)
