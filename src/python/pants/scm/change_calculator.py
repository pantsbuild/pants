# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import re

from pants.build_graph.source_mapper import SpecSourceMapper
from pants.goal.workspace import ScmWorkspace


logger = logging.getLogger(__name__)


class ChangeCalculator(object):
  """A utility for calculating changed files."""

  def __init__(self, scm, workspace=None, changes_since=None, diffspec=None):
    self._scm = scm
    self._workspace = workspace or ScmWorkspace(scm)
    self._changes_since = changes_since
    self._diffspec = diffspec

  def changed_files(self, changed_request=None):
    """Determines the files changed according to SCM/workspace and options."""
    if changed_request:
      changes_since = changed_request.changes_since
      diffspec = changed_request.diffspec
    else:
      changes_since = self._changes_since
      diffspec = self._diffspec

    changes_since = changes_since or self._scm.current_rev_identifier()
    return self._workspace.changes_in(diffspec) if diffspec else self._workspace.touched_files(
      changes_since)


class BuildGraphChangeCalculator(ChangeCalculator):
  """A utility for calculating changed files or changed target addresses."""

  def __init__(self,
               scm,
               workspace,
               address_mapper,
               build_graph,
               include_dependees,
               fast=False,
               changes_since=None,
               diffspec=None,
               exclude_target_regexp=None):
    super(BuildGraphChangeCalculator, self).__init__(scm, workspace, changes_since, diffspec)
    self._address_mapper = address_mapper
    self._build_graph = build_graph
    self._include_dependees = include_dependees
    self._fast = fast
    self._exclude_target_regexp = exclude_target_regexp or []

    self._mapper_cache = None

  @property
  def _mapper(self):
    if self._mapper_cache is None:
      self._mapper_cache = SpecSourceMapper(self._address_mapper, self._build_graph, self._fast)
    return self._mapper_cache

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
    for address in self._address_mapper.scan_addresses():
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
