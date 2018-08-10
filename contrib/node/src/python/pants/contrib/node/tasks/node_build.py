# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from collections import defaultdict

from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.goal.products import MultipleRootedProducts
from pants.util.contextutil import pushd
from pants.util.dirutil import absolute_symlink

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

  def _run_build_script(self, target, results_dir, node_installed_path, node_paths):
    target_address = target.address.reference()
    # If there is build script defined, run the build script and return build output directory;
    # If there is not build script defined, use installation directory as build output.
    if target.payload.build_script:
      self.context.log.info('Running node build {} for {} at {}\n'.format(
        target.payload.build_script, target_address, node_installed_path))
      result, build_command = self.run_script(
        target.payload.build_script,
        target=target,
        node_paths=node_paths,
        workunit_name=target_address,
        workunit_labels=[WorkUnitLabel.COMPILER]
      )
      # Make sure script run is successful.
      if result != 0:
        raise TaskError(
          'Failed to run build for {}:\n\t{} failed with exit code {}'.format(
            target_address, build_command, result))

  def _get_output_dir(self, target, node_installed_path):
    return os.path.normpath(os.path.join(
      node_installed_path,
      target.payload.output_dir if target.payload.build_script else ''))

  def execute(self):
    node_paths = self.context.products.get_data(NodePaths)
    runtime_classpath_product = self.context.products.get_data(
      'runtime_classpath', init_func=ClasspathProducts.init_func(self.get_options().pants_workdir))
    bundleable_js_product = self.context.products.get_data(
      'bundleable_js', init_func=lambda: defaultdict(MultipleRootedProducts))

    targets = self.context.targets(predicate=self.is_node_module)
    with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.all_vts:
        target = vt.target
        node_installed_path = node_paths.node_path(target)

        with pushd(node_installed_path):
          if not vt.valid:
            self._run_build_script(
              target, vt.results_dir, node_installed_path, node_paths.all_node_paths)
          if not target.payload.dev_dependency:
            output_dir = self._get_output_dir(target, node_installed_path)
            # Make sure that there is output generated.
            if not os.path.exists(output_dir):
              raise TaskError(
                'Target {} has build script {} specified, but did not generate any output '
                'at {}.\n'.format(
                  target.address.reference(), target.payload.build_script, output_dir))
            absolute_symlink(output_dir, os.path.join(vt.results_dir, target.address.target_name))
            bundleable_js_product[target].add_abs_paths(output_dir, [output_dir])
            runtime_classpath_product.add_for_target(target, [('default', vt.results_dir)])
