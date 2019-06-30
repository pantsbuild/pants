# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from hashlib import sha1

from pants.base.build_environment import get_buildroot
from pants.base.fingerprint_strategy import DefaultFingerprintHashingMixin, FingerprintStrategy
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.build_graph import sort_targets

from pants.contrib.node.tasks.node_paths import NodePaths, NodePathsLocal
from pants.contrib.node.tasks.node_task import NodeTask


class NodeResolveFingerprintStrategy(DefaultFingerprintHashingMixin, FingerprintStrategy):
  """
  Fingerprint package lockfiles (e.g. package.json, yarn.lock...),
  so that we don't automatically run this if none of those have changed.

  We read every file and add its contents to the hash.
  """

  _package_manager_lockfiles = {
    'yarn': ['package.json', 'yarn.lock'],
    'npm': ['package.json', 'package-lock.json', 'npm-shrinkwrap.json']
  }

  def _get_files_to_watch(self, target):
    package_manager = target.payload.get_field_value("package_manager", '')
    # NB: Defaults to empty list for things like scalajs ad-hoc packages.
    lockfiles = self._package_manager_lockfiles.get(package_manager, [])
    paths = [os.path.join(target.address.spec_path, name) for name in lockfiles]
    return paths

  def compute_fingerprint(self, target):
    if NodeResolve.can_resolve_target(target):
      hasher = sha1()
      for lockfile_path in self._get_files_to_watch(target):
        absolute_lockfile_path = os.path.join(get_buildroot(), lockfile_path)
        # NB: It should not be up to the caching to decide what happens when a
        # lockfile is not added in sources.
        if os.path.exists(absolute_lockfile_path):
          with open(absolute_lockfile_path, 'r') as lockfile:
            contents = lockfile.read().encode()
            hasher.update(contents)
      return hasher.hexdigest()
    return None


class NodeResolve(NodeTask):
  """Resolves node_package targets to their node paths using different registered resolvers.

  This task exposes two products NodePaths and NodePathsLocal. Both products are handled
  optionally allowing the consumer to choose.

  NodePaths contain a mapping of targets and their resolved path in the virtualized
  pants working directory.

  NodePathsLocal is similar to NodePaths with the difference that the resolved path
  is within the same directory that the target is defined.

  A node path is considered resolved if the source files are present, installed all dependencies,
  and have executed their build scripts if defined.
  """

  _resolver_by_type = dict()

  @classmethod
  def product_types(cls):
    return [NodePaths, NodePathsLocal]

  @classmethod
  def prepare(cls, options, round_manager):
    """Allow each resolver to declare additional product requirements."""
    super().prepare(options, round_manager)
    for resolver in cls._resolver_by_type.values():
      resolver.prepare(options, round_manager)

  @property
  def cache_target_dirs(self):
    return True

  @classmethod
  def register_resolver_for_type(cls, node_package_type, resolver):
    """Register a NodeResolver instance for a particular subclass of NodePackage.
    Implementation uses a hash on node_package_type, so the resolver will only be used on the
    exact NodePackage subclass (not further subclasses of it).

    :param class node_package_type: A NodePackage subclass
    :param class resolver: A NodeResolverBase subclass
    """
    cls._resolver_by_type[node_package_type] = resolver

  @classmethod
  def _clear_resolvers(cls):
    """Remove all resolvers.

    This method is EXCLUSIVELY for use in tests.
    """
    cls._resolver_by_type.clear()

  @classmethod
  def _resolver_for_target(cls, target):
    """Get the resolver registered for a target's type, or None if there is none.

    :param NodePackage target: A subclass of NodePackage.
    :rtype: NodeResolver
    """
    return cls._resolver_by_type.get(type(target))

  @classmethod
  def can_resolve_target(cls, target):
    """Returns whether this is a NodePackage and there a resolver registered for its subtype.

    :param target: A Target
    :rtype: Boolean
    """
    return cls.is_node_package(target) and cls._resolver_for_target(target) != None

  def _topological_sort(self, targets):
    """Topologically order a list of targets"""

    target_set = set(targets)
    return [t for t in reversed(sort_targets(targets)) if t in target_set]

  def execute(self):
    targets = self.context.targets(predicate=self.can_resolve_target)
    if not targets:
      return
    if self.context.products.is_required_data(NodePaths):
      node_paths = self.context.products.get_data(NodePaths, init_func=NodePaths)
      # We must have copied local sources into place and have node_modules directories in place for
      # internal dependencies before installing dependees, so `topological_order=True` is critical.
      with self.invalidated(targets,
                            topological_order=True,
                            invalidate_dependents=True,
                            fingerprint_strategy=NodeResolveFingerprintStrategy()
           ) as invalidation_check:
        with self.context.new_workunit(name='install', labels=[WorkUnitLabel.MULTITOOL]):
          for vt in invalidation_check.all_vts:
            target = vt.target
            if not vt.valid:
              resolver_for_target_type = self._resolver_for_target(target).global_instance()
              resolver_for_target_type.resolve_target(self, target, vt.results_dir, node_paths)
            node_paths.resolved(target, vt.results_dir)
    if self.context.products.is_required_data(NodePathsLocal):
      node_paths_local = self.context.products.get_data(NodePathsLocal, init_func=NodePathsLocal)
      # Always resolve targets if NodePathsLocal is required.
      # This is crucial for `node-install` goal which builds against source code and relies on
      # latest and nothing from the pants cache. The caching is done locally via the node_modules
      # directory within source and managed by the underlying package manager. In the future,
      # it can possible to be able to reuse work from the private pants copy.
      sorted_targets = self._topological_sort(targets)
      with self.context.new_workunit(name='node-install', labels=[WorkUnitLabel.MULTITOOL]):
        for target in sorted_targets:
          resolver_for_target_type = self._resolver_for_target(target).global_instance()
          results_dir = os.path.join(get_buildroot(), target.address.spec_path)
          resolver_for_target_type.resolve_target(self, target, results_dir, node_paths_local,
                                                  resolve_locally=True,
                                                  install_optional=True,
                                                  frozen_lockfile=False)
          node_paths_local.resolved(target, results_dir)
