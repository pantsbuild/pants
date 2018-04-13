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


class NodeRun(NodeTask):
  """Runs a script specified in a package.json file, currently through "npm run [script name]"."""

  @classmethod
  def register_options(cls, register):
    super(NodeRun, cls).register_options(register)
    register('--script-name', default='start',
             help='The script name to run.')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def execute(self):
    target = self.require_single_root_target()

    if self.is_node_module(target):
      node_paths = self.context.products.get_data(NodePaths)
      with pushd(node_paths.node_path(target)):
        result, command = self.run_script(
          self.get_options().script_name,
          target=target,
          script_args=self.get_passthru_args(),
          node_paths=node_paths.all_node_paths,
          workunit_name=target.address.reference(),
          workunit_labels=[WorkUnitLabel.RUN])
        if result != 0:
          raise TaskError('Run script failed:\n'
                          '\t{} failed with exit code {}'.format(command, result))
