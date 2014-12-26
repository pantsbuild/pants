# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.exceptions import TaskError
from pants.base.lazy_source_mapper import LazySourceMapper


class ChangedFileTaskMixin(object):
  """A mixin for tasks which require the set of targets (or files) changed according to SCM.

  Changes are calculated relative to a ref/tree-ish (defaults to HEAD), and changed files are then
  mapped to targets using LazySourceMapper. LazySourceMapper can optionally be used in "fast" mode,
  which stops searching for additional owners for a given source once a one is found.
  """
  @classmethod
  def register_change_file_options(cls, register):
    register('--fast', action='store_true', default=False,
             help='Stop searching for owners once a source is mapped to at least owning target.')
    register('--changes-since', '--parent',
             help='Calculate changes since this tree-ish/scm ref (defaults to current HEAD/tip).')

  _mapper_cache = None
  @property
  def _mapper(self):
    if self._mapper_cache is None:
      self._mapper_cache = LazySourceMapper(self.context, self.get_options().fast)
    return self._mapper_cache

  def _changed_files(self):
    """Determines the changed files using the SCM workspace and options."""
    if not self.context.workspace:
      raise TaskError('No workspace provided.')
    if not self.context.scm:
      raise TaskError('No SCM available.')
    since = self.get_options().changes_since or self.context.scm.current_rev_identifier()
    return self.context.workspace.touched_files(since)

  def _changed_targets(self):
    """Determine unique target addresses changed mapping scm changed files to targets"""
    targets_for_source = self._mapper.target_addresses_for_source
    return set(addr for src in self._changed_files() for addr in targets_for_source(src))


class WhatChanged(ConsoleTask, ChangedFileTaskMixin):
  """Emits the targets that have been modified since a given commit."""
  @classmethod
  def register_options(cls, register):
    super(WhatChanged, cls).register_options(register)
    cls.register_change_file_options(register)
    register('--files', action='store_true', default=False,
             help='Show changed files instead of the targets that own them.')

  def console_output(self, _):
    if self.get_options().files:
      for f in sorted(self._changed_files()):
        yield f
    else:
      for addr in sorted(self._changed_targets()):
        yield addr.spec
