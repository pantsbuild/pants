# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import shutil

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.util.contextutil import pushd
from pants.util.dirutil import safe_mkdir

from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_task import NodeTask


def _copy_sources(buildroot, node_module, dest_dir):
  source_relative_to = node_module.address.spec_path
  for source in node_module.sources_relative_to_buildroot():
    dest = os.path.join(dest_dir, os.path.relpath(source, source_relative_to))
    safe_mkdir(os.path.dirname(dest))
    shutil.copyfile(os.path.join(buildroot, source), dest)


class NpmResolve(NodeTask):
  """Resolves node modules to isolated chroots.

  See: see `npm install <https://docs.npmjs.com/cli/install>`_
  """

  @classmethod
  def product_types(cls):
    return [NodePaths]

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    # TODO(John Sirois): Is there a way to avoid a naive re-resolve for each target, ie bulk
    # resolve and then post-resolve analyze the results locally to create a separate NODE_PATH
    # for each target participating in the bulk resolve?  This is unlikely since versions are often
    # unconstrained or partially constrained in the npm community.
    # See TODO in NodePaths re: UnionProducts.
    targets = set(self.context.targets(predicate=self.is_npm_package))
    if not targets:
      return

    node_paths = self.context.products.get_data(NodePaths, init_func=NodePaths)

    # We must have linked local sources for internal dependencies before installing dependees; so,
    # `topological_order=True` is critical.
    with self.invalidated(targets,
                          topological_order=True,
                          invalidate_dependents=True) as invalidation_check:

      with self.context.new_workunit(name='install', labels=[WorkUnitLabel.MULTITOOL]):
        for vt in invalidation_check.all_vts:
          target = vt.target
          chroot = vt.results_dir
          if not vt.valid:
            safe_mkdir(chroot, clean=True)
            self._resolve(target, chroot, node_paths)
          node_paths.resolved(target, chroot)

  def _resolve(self, target, node_path, node_paths):
    # Only resolve local targets, while we don't have a way to cache 3rd party targets individually
    if self.is_node_module(target):
      self._resolve_local_module(node_path, node_paths, target)

  def _resolve_local_module(self, node_path, node_paths, node_module):
    _copy_sources(buildroot=get_buildroot(), node_module=node_module, dest_dir=node_path)
    self._emit_package_descriptor(node_module, node_path, node_paths)
    with pushd(node_path):
      # TODO(John Sirois): Handle dev dependency resolution.
      result, npm_install = self.execute_npm(args=['install'],
                                             workunit_name=node_module.address.reference())
      if result != 0:
        raise TaskError('Failed to resolve dependencies for {}:\n\t{} failed with exit code {}'
                        .format(node_module.address.reference(), npm_install, result))

  def _emit_package_descriptor(self, npm_package, node_path, node_paths):
    package_json_path = os.path.join(node_path, 'package.json')

    if os.path.isfile(package_json_path):
      with open(package_json_path, 'r') as fp:
        package = json.load(fp)
    else:
      package = {}

    if not package.has_key('name'):
      package['name'] = npm_package.package_name
    elif package['name'] != npm_package.package_name:
      raise TaskError('Package name in the corresponding package.json is not the same '
                      'as the BUILD target name for {}'.format(npm_package.address.reference()))

    if not package.has_key('version'):
      package['version'] = '0.0.0'

    # Preserve compatibility with normal package.json files. Update any
    # local dependencies in the package.json to reflect their paths under .pants.d
    # by using the corresponding Pants BUILD file target. Use any node_remote_module BUILD file
    # targets to check the versions of 3rd party dependencies declared in package.json, but don't
    # require them to be present. Finally, allow dependencies to be specified in BUILD file targets
    # and not in package.json at all. Fill in the package.json with any BUILD file targets it
    # doesn't have.
    # TODO(Chris Pesto): We should require all local targets in a package.json to be present in
    # a BUILD file node_module target. This isn't checking that, which is a loophole.
    target_deps_by_name = {dep.package_name: dep for dep in npm_package.dependencies}
    all_package_deps = set()

    dependency_types_to_check = [
      'dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'
    ]
    for dependency_type in dependency_types_to_check:
      package_deps_of_type = package.get(dependency_type, {})
      all_package_deps.update(package_deps_of_type.keys())
      for package_name, package_version in package_deps_of_type.items()[:]:
        package_dep_target = target_deps_by_name.get(package_name, None)
        if self.is_node_module(package_dep_target):
          package[package_deps_of_type][package_name] = node_paths.node_path(package_dep_target)
        elif self.is_node_remote_module(package_dep_target):
          if package_dep_target.version != package_version:
            raise TaskError('BUILD files specify that the target {} depends on {} version {}, '
                            'but its package.json specifies a dependency on version {}'
                            .format(npm_package.address.reference(), package_name,
                                    package_dep_target.version, package_version))

    target_deps_not_in_package = set(target_deps_by_name.keys()) - all_package_deps
    if target_deps_not_in_package:
      package_normal_deps = package.setdefault('dependencies', {})
      for package_name in target_deps_not_in_package:
        target_dep = target_deps_by_name[package_name]
        package_normal_deps[package_name] = (node_paths.node_path(target_dep)
                                             if self.is_node_module(target_dep)
                                             else target_dep.version)

    with open(package_json_path, 'wb') as fp:
      json.dump(package, fp, indent=2)
