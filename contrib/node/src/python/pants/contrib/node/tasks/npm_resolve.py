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
          node_path = chroot if self.is_node_module(target) else os.path.join(chroot,
                                                                              'node_modules')
          node_paths.resolved(target, node_path)

  def _resolve(self, target, node_path, node_paths):
    if self.is_node_remote_module(target):
      self._resolve_remote_module(node_path, target)
    else:
      self._resolve_local_module(node_path, node_paths, target)

  def _resolve_remote_module(self, node_path, node_remote_module):
    with pushd(node_path):
      package = '{}@{}'.format(node_remote_module.package_name, node_remote_module.version)
      result, npm_install = self.execute_npm(args=['install', package],
                                             workunit_name=node_remote_module.address.reference())
      if result != 0:
        raise TaskError('Failed to resolve package {} for {}:\n\t{} failed with exit code {}'
                        .format(node_remote_module.address.reference(),
                                package,
                                npm_install,
                                result))

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

      # TODO(John Sirois): This will be part of install in npm 3.x, detect or control the npm
      # version we use and only conditionally execute this.
      result, npm_dedupe = self.execute_npm(args=['dedupe'],
                                            workunit_name=node_module.address.reference())
      if result != 0:
        raise TaskError('Failed to dedupe dependencies for {}:\n\t{} failed with exit code {}'
                        .format(node_module.address.reference(), npm_dedupe, result))

  def _emit_package_descriptor(self, npm_package, node_path, node_paths):
    def render_dep(target):
      return node_paths.node_path(target) if self.is_node_module(target) else target.version
    dependencies = {dep.package_name: render_dep(dep) for dep in npm_package.dependencies}

    package = {
      'name': npm_package.package_name,
      'version': '0.0.0',
      'dependencies': dependencies
    }
    with open(os.path.join(node_path, 'package.json'), 'wb') as fp:
      json.dump(package, fp, indent=2)
