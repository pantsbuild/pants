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

  def __init__(self, *args, **kwargs):
    super(NodeBuild, self).__init__(*args, **kwargs)

  def execute(self):
    node_paths = self.context.products.get_data(NodePaths)
    runtime_classpath_product = self.context.products.get_data('runtime_classpath')
    bundleable_js_product = self.context.products.get_data(
      'bundleable_js', lambda: defaultdict(MultipleRootedProducts))

    for target in self.context.targets(predicate=self.is_node_module):
      if self.is_node_module(target):
        target_address = target.address.reference()
        node_installed_path = node_paths.node_path(target)

        self.context.log.debug('Running node build for {} at {}\n'.format(
          target_address, node_installed_path))

        with pushd(node_installed_path):

          if target.payload.build_script:
            result, npm_build_command = self.execute_npm(
              ['run-script', target.payload.build_script],
              workunit_name=target_address,
              workunit_labels=[WorkUnitLabel.COMPILER])
            if result != 0:
              raise TaskError(
                'Failed to run build for {}:\n\t{} failed with exit code {}'.format(
                  target_address, npm_build_command, result))
            output_dir = os.path.join(
              node_installed_path,
              target.payload.output_dir)
            if not os.path.exists(output_dir):
              raise TaskError(
                'Failed to run build for {}:\n\t{} did not generate any output at {}'.format(
                  target_address, npm_build_command, output_dir))
            else:
              self.context.log.debug('node build output {}\n'.format(output_dir))

            self.context.log.info('Adding {} to runtime_classpath\n'.format(output_dir))

            # Resources included in a JAR file will be under %target_name%/%output_dir%
            tmp_dir = safe_mkdtemp(dir=node_installed_path)
            assets_dir = os.path.join(
              tmp_dir, target.address.target_name, os.path.dirname(target.payload.output_dir))
            safe_mkdir(assets_dir, clean=True)
            absolute_symlink(
              output_dir, os.path.join(assets_dir, os.path.basename(target.payload.output_dir)))
            runtime_classpath_product.add_for_target(target, [('default', tmp_dir)])
            bundleable_js_product[target].add_abs_paths(output_dir, [output_dir])
          else:
            bundleable_js_product[target].add_abs_paths(output_dir, [node_installed_path])
