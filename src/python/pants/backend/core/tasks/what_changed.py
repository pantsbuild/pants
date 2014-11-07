# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.base.exceptions import TaskError
from pants.goal.workspace import Workspace


class WhatChanged(ConsoleTask):
  """Emits the targets that have been modified since a given commit."""
  @classmethod
  def register_options(cls, register):
    super(WhatChanged, cls).register_options(register)
    register('--parent', default='HEAD', legacy='what_changed_create_prefix',
             help='Calculate changes against this tree-ish.')
    register('--files', action='store_true', default=False, legacy='what_changed_show_files',
             help='Show changed files instead of the targets that own them.')

  def __init__(self, *args, **kwargs):
    super(WhatChanged, self).__init__(*args, **kwargs)
    self._parent = self.get_options().parent
    self._show_files = self.get_options().files
    self._workspace = self.context.workspace
    self._filemap = {}

  def console_output(self, _):
    if not self._workspace:
      raise TaskError('No workspace provided.')

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
            yield touched_target.address.spec

  def _get_touched_files(self):
    try:
      return self._workspace.touched_files(self._parent)
    except Workspace.WorkspaceError as e:
      raise TaskError(e)

  def _owning_targets(self, path):
    for build_file in self._candidate_owners(path):
      build_graph = self.context.build_graph
      build_file_parser = self.context.build_file_parser
      address_map = build_file_parser.parse_build_file(build_file)
      for address, _ in address_map.items():
        build_graph.inject_address_closure(address)
      is_build_file = (build_file.full_path == os.path.join(get_buildroot(), path))

      for target in build_graph.targets():
        # HACK: Python targets currently wrap old-style file resources in a synthetic
        # resources target, but they do so lazily, when target.resources is first accessed.
        # We force that access here, so that the targets will show up in the subsequent
        # invocation of build_graph.targets().
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
