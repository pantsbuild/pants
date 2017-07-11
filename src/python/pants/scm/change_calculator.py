# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import re
from abc import abstractmethod

from pants.base.specs import DescendantAddresses
from pants.build_graph.source_mapper import SpecSourceMapper
from pants.goal.workspace import ScmWorkspace
from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


class ChangeCalculator(AbstractClass):
  """An abstract class for changed target calculation."""

  def __init__(self, scm, workspace=None, changes_since=None, diffspec=None):
    self._scm = scm
    self._workspace = workspace or ScmWorkspace(scm)
    self._changes_since = changes_since
    self._diffspec = diffspec

  def changed_files(self, changes_since=None, diffspec=None):
    """Determines the files changed according to SCM/workspace and options."""
    diffspec = diffspec or self._diffspec
    if diffspec:
      return self._workspace.changes_in(diffspec)

    changes_since = changes_since or self._changes_since or self._scm.current_rev_identifier()
    return self._workspace.touched_files(changes_since)

  @abstractmethod
  def changed_target_addresses(self):
    """Find changed targets, according to SCM."""


# TODO: Remove this in 1.5.0dev0 in favor of `EngineChangeCalculator`.
class BuildGraphChangeCalculator(ChangeCalculator):
  """A `BuildGraph`-based helper for calculating changed target addresses."""

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
    self._build_graph = build_graph
    self._include_dependees = include_dependees
    self._fast = fast
    self._exclude_target_regexp = exclude_target_regexp or []
    self._mapper = SpecSourceMapper(address_mapper, build_graph, fast)

  def _directly_changed_targets(self):
    # Internal helper to find target addresses containing SCM changes.
    targets_for_source = self._mapper.target_addresses_for_source
    result = set()
    for src in self.changed_files(self._changes_since, self._diffspec):
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
    for _ in self._build_graph.inject_specs_closure([DescendantAddresses('')]):
      pass

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
