# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import OrderedDict

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.tasks2.pex_build_util import (dump_sources, has_python_sources,
                                                        has_resources, is_python_target)
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.task.task import Task
from pants.util.dirutil import safe_concurrent_creation


class GatherSources(Task):
  """Gather local Python sources.

  Creates one or more (unzipped) PEXs on disk containing the local Python sources.
  These PEXes can be merged with a requirements PEX to create a unified Python environment
  for running the relevant python code.
  """

  class PythonSources(object):
    """A mapping of unzipped source PEXs by the targets whose sources the PEXs contain."""

    class UnmappedTargetError(Exception):
      """Indicates that no python source pex could be found for a given target."""

    def __init__(self, pex_by_target_base):
      self._pex_by_target_base = pex_by_target_base

    def for_target(self, target):
      """Return the unzipped PEX containing the given target's sources.

      :returns: An unzipped PEX containing at least the given target's sources.
      :rtype: :class:`pex.pex.PEX`
      :raises: :class:`GatherSources.PythonSources.UnmappedTargetError` if no pex containing the
               given target's sources could be found.
      """
      pex = self._pex_by_target_base.get(target.target_base)
      if pex is None:
        raise self.UnmappedTargetError()
      return pex

    def all(self):
      """Return all the unzipped source PEXs needed for this round."""
      return self._pex_by_target_base.values()

  @classmethod
  def implementation_version(cls):
    return super(GatherSources, cls).implementation_version() + [('GatherSources', 4)]

  @classmethod
  def product_types(cls):
    return [cls.PythonSources]

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)
    round_manager.require_data('python')  # For codegen.

  def execute(self):
    interpreter = self.context.products.get_data(PythonInterpreter)

    pex_by_target_base = OrderedDict()  # Preserve ~PYTHONPATH ordering over pexes.
    for target_base, targets in self._iter_targets_by_base():
      with self.invalidated(targets) as invalidation_check:
        pex = self._get_pex_for_versioned_targets(interpreter, invalidation_check.all_vts)
        pex_by_target_base[target_base] = pex
    self.context.products.register_data(self.PythonSources, self.PythonSources(pex_by_target_base))

  def _iter_targets_by_base(self):
    # N.B: Files and Resources targets belong with the consuming (dependee) targets so that those
    # targets can be ensured of access to the files in their PEX chroot. This means a given Files
    # or Resources target could be embedded in multiple pexes.

    context = self.context
    python_target_addresses = [p.address for p in context.targets(predicate=is_python_target)]

    targets_by_base = OrderedDict()  # Preserve ~PYTHONPATH ordering over source roots.
    resource_targets = set()

    def collect_source_targets(target):
      if has_python_sources(target):
        targets = targets_by_base.get(target.target_base)
        if targets is None:
          targets = set()
          targets_by_base[target.target_base] = targets
        targets.add(target)
      elif has_resources(target):
        resource_targets.add(target)

    build_graph = context.build_graph
    build_graph.walk_transitive_dependency_graph(addresses=python_target_addresses,
                                                 work=collect_source_targets)

    for resource_target in resource_targets:
      dependees = build_graph.transitive_dependees_of_addresses([resource_target.address])
      for target_base, targets in targets_by_base.items():
        for dependee in dependees:
          if dependee in targets:
            # N.B.: This can add the resource to too many pexes. A canonical example is
            # test -> lib -> resource where test and lib have separate source roots. In this case
            # the resource is added to both the test pex and the lib pex and it's only needed in the
            # lib pex. The upshot is we allow python code access to undeclared (ie: indirect)
            # resource dependencies which is no worse than historical precedent, but could be
            # improved with a more complex algorithm.
            targets.add(resource_target)
            break

    return targets_by_base.items()

  def _get_pex_for_versioned_targets(self, interpreter, versioned_targets):
    if versioned_targets:
      target_set_id = VersionedTargetSet.from_versioned_targets(versioned_targets).cache_key.hash
    else:
      # If there are no relevant targets, we still go through the motions of gathering
      # an empty set of sources, to prevent downstream tasks from having to check
      # for this special case.
      target_set_id = 'no_targets'
    source_pex_path = os.path.realpath(os.path.join(self.workdir, target_set_id))
    # Note that we check for the existence of the directory, instead of for invalid_vts,
    # to cover the empty case.
    if not os.path.isdir(source_pex_path):
      # Note that we use the same interpreter for all targets: We know the interpreter
      # is compatible (since it's compatible with all targets in play).
      with safe_concurrent_creation(source_pex_path) as safe_path:
        self._build_pex(interpreter, safe_path, [vt.target for vt in versioned_targets])
    return PEX(source_pex_path, interpreter=interpreter)

  def _build_pex(self, interpreter, path, targets):
    builder = PEXBuilder(path=path, interpreter=interpreter, copy=True)
    for target in targets:
      dump_sources(builder, target, self.context.log)
    builder.freeze()
