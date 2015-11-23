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


def _copy_sources(buildroot, target, results_dir):
  source_relative_to = target.address.spec_path
  for source in target.sources_relative_to_buildroot():
    dest = os.path.join(results_dir, os.path.relpath(source, source_relative_to))
    safe_mkdir(os.path.dirname(dest))
    shutil.copyfile(os.path.join(buildroot, source), dest)


class NodeResolve(NodeTask):
  """Resolves node_package targets to isolated chroots using different registered resolvers."""

  @classmethod
  def product_types(cls):
    return [NodePaths]

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    targets = set(self.context.targets(predicate=self.is_node_module))
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
          results_dir = vt.results_dir
          if not vt.valid:
            safe_mkdir(results_dir, clean=True)
            self._resolve(target, results_dir, node_paths)
          node_paths.resolved(target, results_dir)

  def _resolve(self, target, results_dir, node_paths):
    _copy_sources(get_buildroot(), target, results_dir)
    self._emit_package_descriptor(target, results_dir, node_paths)
    with pushd(results_dir):
      # TODO(John Sirois): Handle dev dependency resolution.
      result, npm_install = self.execute_npm(args=['install'],
                                             workunit_name=target.address.reference(),
                                             workunit_labels=[WorkUnitLabel.COMPILER])
      if result != 0:
        raise TaskError('Failed to resolve dependencies for {}:\n\t{} failed with exit code {}'
                        .format(target.address.reference(), npm_install, result))

  def _emit_package_descriptor(self, target, results_dir, node_paths):
    dependencies = {
      dep.package_name: self.render_node_package_dependency(node_paths, dep)
                        for dep in target.dependencies
    }

    package_json_path = os.path.join(results_dir, 'package.json')

    if os.path.isfile(package_json_path):
      with open(package_json_path, 'r') as fp:
        package = json.load(fp)
    else:
      package = {}

    if not package.has_key('name'):
      package['name'] = target.package_name
    elif package['name'] != target.package_name:
      raise TaskError('Package name in the corresponding package.json is not the same '
                      'as the BUILD target name for {}'.format(target.address.reference()))

    if not package.has_key('version'):
      package['version'] = '0.0.0'

    # TODO(Chris Pesto): Preserve compatibility with normal package.json files by dropping existing
    # dependency fields. This lets Pants accept working package.json files from standalone projects
    # that can be "npm install"ed without Pants. Taking advantage of this means expressing
    # dependencies in package.json and BUILD, though. In the future, work to make
    # Pants more compatible with package.json to eliminate duplication if you still want your
    # project to "npm install" through NPM by itself.
    dependenciesToRemove = [
      'dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'
    ]
    for dependencyType in dependenciesToRemove:
      package.pop(dependencyType, None)

    package['dependencies'] = dependencies

    with open(package_json_path, 'wb') as fp:
      json.dump(package, fp, indent=2)
