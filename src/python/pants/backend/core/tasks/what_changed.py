# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from itertools import chain
import re

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
    register('--diffspec',
             help='Calculate changes contained within given scm spec (commit range/sha/ref/etc).')
    register('--include-dependees', choices=['none', 'direct', 'transitive'], default='none',
             help='Include direct or transitive dependees of changed targets.')


  _mapper_cache = None
  @property
  def _mapper(self):
    if self._mapper_cache is None:
      self._mapper_cache = LazySourceMapper(self.context, self.get_options().fast)
    return self._mapper_cache

  def _changed_files(self):
    """Determines the files changed according to SCM/workspace and options."""
    if not self.context.workspace:
      raise TaskError('No workspace provided.')
    if not self.context.scm:
      raise TaskError('No SCM available.')
    if self.get_options().diffspec:
      self.context.log.info('Finding changes in {}'.format(self.get_options().diffspec))
      return self.context.workspace.changes_in(self.get_options().diffspec)
    else:
      since = self.get_options().changes_since or self.context.scm.current_rev_identifier()
      return self.context.workspace.touched_files(since)

  def _directly_changed_targets(self):
    """Internal helper to find target addresses containing SCM changes."""
    targets_for_source = self._mapper.target_addresses_for_source
    files = self._changed_files()
    self.context.log.info('Changed files: ' + ','.join(files))
    return set(addr for src in files for addr in targets_for_source(src))

  def _find_changed_targets(self):
    """Internal helper to find changed targets, optionally including their dependees."""
    build_graph = self.context.build_graph
    dependees_inclusion = self.get_options().include_dependees

    changed = self._directly_changed_targets()

    # Skip loading the graph or doing any further work if no directly changed targets found.
    if not changed:
      return changed

    if dependees_inclusion == 'none':
      return changed

    # Load the whole build graph since we need it for dependee finding in either remaining case.
    for address in self.context.address_mapper.scan_addresses():
      build_graph.inject_address_closure(address)

    if dependees_inclusion == 'direct':
      return changed.union(*[build_graph.dependents_of(addr) for addr in changed])

    if dependees_inclusion == 'transitive':
      return set(t.address for t in build_graph.transitive_dependees_of_addresses(changed))

    # Should never get here.
    raise ValueError('Unknown dependee inclusion: "{}"'.format(dependees_inclusion))

  def _changed_targets(self):
    """Find changed targets, according to SCM.

    This is the intended entry point for finding changed targets unless callers have a specific
    reason to call one of the above internal helpers. It will find changed targets and:
      - Optionally find changes in a given diffspec (commit, branch, tag, range, etc).
      - Optionally include direct or transitive dependees.
      - Optionally filter targets matching exclude_target_regexp.
    """
    # Find changed targets (and maybe their dependees).
    changed = self._find_changed_targets()

    # Remove any that match the exclude_target_regexp list.
    excludes = [re.compile(pattern) for pattern in self.get_options().exclude_target_regexp]
    ret = set([
      t for t in changed if not any(exclude.search(t.spec) is not None for exclude in excludes)
    ])

    excluded = changed - ret
    if excluded:
      self.context.log.info('Ignoring changes to targets: ', *excluded)
    return ret


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
