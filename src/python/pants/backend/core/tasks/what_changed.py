# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.build_environment import get_scm
from pants.base.exceptions import TaskError
from pants.build_graph.source_mapper import SpecSourceMapper
from pants.goal.workspace import ScmWorkspace


class ChangeCalculator(object):
  """A utility for calculating changed files or changed target addresses."""

  def __init__(self,
               scm,
               workspace,
               address_mapper,
               build_graph,
               fast=False,
               changes_since=None,
               diffspec=None,
               include_dependees=None,
               exclude_target_regexp=None,
               spec_excludes=None):

    self._scm = scm
    self._workspace = workspace
    self._address_mapper = address_mapper
    self._build_graph = build_graph

    self._fast = fast
    self._changes_since = changes_since
    self._diffspec = diffspec
    self._include_dependees = include_dependees
    self._exclude_target_regexp = exclude_target_regexp
    self._spec_excludes = spec_excludes

    self._mapper_cache = None

  @property
  def _mapper(self):
    if self._mapper_cache is None:
      self._mapper_cache = SpecSourceMapper(self._address_mapper, self._build_graph, self._fast)
    return self._mapper_cache

  def changed_files(self):
    """Determines the files changed according to SCM/workspace and options."""
    if self._diffspec:
      return self._workspace.changes_in(self._diffspec)
    else:
      since = self._changes_since or self._scm.current_rev_identifier()
      return self._workspace.touched_files(since)

  def _directly_changed_targets(self):
    # Internal helper to find target addresses containing SCM changes.
    targets_for_source = self._mapper.target_addresses_for_source
    result = set()
    for src in self.changed_files():
      result.update(set(targets_for_source(src)))
    return result

  def _find_changed_targets(self):
    # Internal helper to find changed targets, optionally including their dependees.
    changed = self._directly_changed_targets()

    # Skip loading the graph or doing any further work if no directly changed targets found.
    if not changed:
      return changed

    if self._include_dependees == 'none':
      return changed

    # Load the whole build graph since we need it for dependee finding in either remaining case.
    for address in self._address_mapper.scan_addresses(spec_excludes=self._spec_excludes):
      self._build_graph.inject_address_closure(address)

    if self._include_dependees == 'direct':
      return changed.union(*[self._build_graph.dependents_of(addr) for addr in changed])

    if self._include_dependees == 'transitive':
      return set(t.address for t in self._build_graph.transitive_dependees_of_addresses(changed))

    # Should never get here.
    raise ValueError('Unknown dependee inclusion: "{}"'.format(self._include_dependees))

  def changed_target_addresses(self):
    """Find changed targets, according to SCM.

    This is the intended entry point for finding changed targets unless callers have a specific
    reason to call one of the above internal helpers. It will find changed targets and:
      - Optionally find changes in a given diffspec (commit, branch, tag, range, etc).
      - Optionally include direct or transitive dependees.
      - Optionally filter targets matching exclude_target_regexp.

    :returns: A set of target addresses.
    """
    # Find changed targets (and maybe their dependees).
    changed = self._find_changed_targets()

    # Remove any that match the exclude_target_regexp list.
    excludes = [re.compile(pattern) for pattern in self._exclude_target_regexp]
    return set([
      t for t in changed if not any(exclude.search(t.spec) is not None for exclude in excludes)
    ])


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

  @classmethod
  def change_calculator(cls, options, address_mapper, build_graph, scm=None, workspace=None, spec_excludes=None):
    scm = scm or get_scm()
    if scm is None:
      raise TaskError('No SCM available.')
    workspace = workspace or ScmWorkspace(scm)

    return ChangeCalculator(scm,
                            workspace,
                            address_mapper,
                            build_graph,
                            fast=options.fast,
                            changes_since=options.changes_since,
                            diffspec=options.diffspec,
                            include_dependees=options.include_dependees,
                            # NB: exclude_target_regexp is a global scope option registered
                            # elsewhere
                            exclude_target_regexp=options.exclude_target_regexp,
                            spec_excludes=spec_excludes)


class WhatChanged(ChangedFileTaskMixin, ConsoleTask):
  """Emits the targets that have been modified since a given commit."""

  @classmethod
  def register_options(cls, register):
    super(WhatChanged, cls).register_options(register)
    cls.register_change_file_options(register)
    register('--files', action='store_true', default=False,
             help='Show changed files instead of the targets that own them.')

  def console_output(self, _):
    spec_excludes = self.get_options().spec_excludes
    change_calculator = self.change_calculator(self.get_options(),
                                               self.context.address_mapper,
                                               self.context.build_graph,
                                               scm=self.context.scm,
                                               workspace=self.context.workspace,
                                               spec_excludes=spec_excludes)
    if self.get_options().files:
      for f in sorted(change_calculator.changed_files()):
        yield f
    else:
      for addr in sorted(change_calculator.changed_target_addresses()):
        yield addr.spec
