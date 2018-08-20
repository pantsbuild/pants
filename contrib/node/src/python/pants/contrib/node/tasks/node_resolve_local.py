# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.base.workunit import WorkUnitLabel

from pants.contrib.node.tasks.node_paths_local import NodePathsLocal
from pants.contrib.node.tasks.node_resolve import NodeResolve


class NodeResolveLocal(NodeResolve):
  """Resolves node_package targets to source chroots using different registered resolvers."""

  @classmethod
  def product_types(cls):
    return [NodePathsLocal]

  @property
  def cache_target_dirs(self):
    # Do not create a results_dir for this task
    return True

  def artifact_cache_reads_enabled(self):
    # Artifact caching is not necessary for local installation.
    # Just depend on the local cache provided by the package manager.
    return self._cache_factory.read_cache_available()

  def execute(self):
    targets = self.context.targets(predicate=self._can_resolve_target)
    if not targets:
      return

    node_paths = self.context.products.get_data(NodePathsLocal, init_func=NodePathsLocal)
    # Invalidate all targets for this task, and use invalidated() check
    # to build topologically sorted target graph. This is probably not the best way
    # to do this, but it works.
    self.invalidate()
    with self.invalidated(targets,
                          # This is necessary to ensure that transitive dependencies are installed first
                          topological_order=True,
                          invalidate_dependents=True,
                          silent=True) as invalidation_check:
      with self.context.new_workunit(name='node-install', labels=[WorkUnitLabel.MULTITOOL]):
        for vt in invalidation_check.all_vts:
          target = vt.target
          if not vt.valid:
            resolver_for_target_type = self._resolver_for_target(target).global_instance()
            results_dir = os.path.abspath(target.address.spec_path)
            resolver_for_target_type.resolve_target(self, target, results_dir, node_paths, resolve_locally=True)
          node_paths.resolved(target, results_dir)
