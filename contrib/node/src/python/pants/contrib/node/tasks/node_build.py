# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.goal.products import MultipleRootedProducts
from pants.util.contextutil import pushd
from pants.util.dirutil import absolute_symlink, safe_mkdir, safe_mkdtemp

from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_task import NodeTask


class NodeBuild(NodeTask):
  """Create an archive bundle of NodeModule targets."""

  @classmethod
  def product_types(cls):
    # runtime_classpath is used for JVM target to include node build results as resources.
    return ['bundleable_js', 'runtime_classpath']

  @classmethod
  def prepare(cls, options, round_manager):
    super(NodeBuild, cls).prepare(options, round_manager)
    round_manager.require_data(NodePaths)

  @property
  def create_target_dirs(self):
    return True

  def __init__(self, *args, **kwargs):
    super(NodeBuild, self).__init__(*args, **kwargs)

  def execute(self):
    node_paths = self.context.products.get_data(NodePaths)
    runtime_classpath_product = self.context.products.get_data('runtime_classpath')
    bundleable_js_product = self.context.products.get_data(
      'bundleable_js', lambda: defaultdict(MultipleRootedProducts))

    targets = self.context.targets(predicate=self.is_node_module)
    with self.invalidated(targets) as invalidation_check:
      for vt in invalidation_check.all_vts:
        target = vt.target
        target_address = target.address.reference()
        node_installed_path = node_paths.node_path(target)

        with pushd(node_installed_path):
          if target.payload.build_script:
            if not vt.valid:
              self.context.log.info('Running node build {} for {} at {}\n'.format(
                target.payload.build_script, target_address, node_installed_path))
              result, npm_build_command = self.execute_npm(
                ['run-script', target.payload.build_script],
                workunit_name=target_address,
                workunit_labels=[WorkUnitLabel.COMPILER])
              if result != 0:
                raise TaskError(
                  'Failed to run build for {}:\n\t{} failed with exit code {}'.format(
                    target_address, npm_build_command, result))

            if target.payload.preserve_artifacts:
              output_dir = os.path.join(node_installed_path, target.payload.output_dir)
              if os.path.exists(output_dir):
                bundleable_js_product[target].add_abs_paths(output_dir, [output_dir])
              else:
                raise TaskError(
                  'Target {} has build script {} specified, but did not generate any output '
                  'at {}.\n'.format(target_address, npm_build_command, output_dir))
          else:
            if target.payload.preserve_artifacts:
              bundleable_js_product[target].add_abs_paths(node_installed_path, [node_installed_path])
              output_dir = node_installed_path

          if target.payload.preserve_artifacts:
            if not vt.valid:
              # Resources included in a JAR file will be under %target_name%
              absolute_symlink(output_dir, os.path.join(vt.results_dir, target.address.target_name))
            self.context.log.debug('adding {} for target {} to runtime classpath'.format(
              vt.results_dir, target_address))
            runtime_classpath_product.add_for_target(target, [('default', vt.results_dir)])

