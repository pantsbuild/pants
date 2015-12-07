# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.util.contextutil import pushd

from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_task import NodeTask


class NodeTest(NodeTask):
  """Runs a test script from package.json in a NodeModule, currently via "npm run [script name]"."""

  @classmethod
  def supports_passthru_args(cls):
    return True

  def execute(self):
    targets = set(self.context.targets(predicate=self.is_node_test))
    if not targets:
      return

    node_paths = self.context.products.get_data(NodePaths)

    for target in targets:
      node_module_dependencies = [dep for dep in target.dependencies if self.is_node_module(dep)]

      for dep in node_module_dependencies:
        node_path = node_paths.node_path(dep)

        args = ['run', target.script_name] + self.get_passthru_args()

        with pushd(node_path):
          result, npm_run = self.execute_npm(args=args,
                                             workunit_labels=[WorkUnitLabel.TEST])
          if result != 0:
            raise TaskError('npm run script failed:\n'
                            '\t{} failed with exit code {}'.format(npm_run, result))
