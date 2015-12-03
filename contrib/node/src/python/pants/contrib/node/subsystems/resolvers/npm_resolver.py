# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import pushd

from pants.contrib.node.subsystems.resolvers.node_resolver_base import NodeResolverBase
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.tasks.node_resolve import NodeResolve


class NpmResolver(Subsystem, NodeResolverBase):
  options_scope = 'npm-resolver'

  @classmethod
  def register_options(cls, register):
    super(NpmResolver, cls).register_options(register)
    NodeResolve.register_resolver_for_type(NodeModule, cls)

  def resolve_target(self, node_task, target, results_dir, node_paths):
    self._copy_sources(target, results_dir)
    self._emit_package_descriptor(node_task, target, results_dir, node_paths)
    with pushd(results_dir):
      result, npm_install = node_task.execute_npm(args=['install'],
                                                  workunit_name=target.address.reference(),
                                                  workunit_labels=[WorkUnitLabel.COMPILER])
      if result != 0:
        raise TaskError('Failed to resolve dependencies for {}:\n\t{} failed with exit code {}'
                        .format(target.address.reference(), npm_install, result))

  def _emit_package_descriptor(self, node_task, target, results_dir, node_paths):
    dependencies = {
      dep.package_name: node_paths.node_path(dep) if node_task.is_node_module(dep) else dep.version
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
