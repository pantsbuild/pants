# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.contrib.node.tasks.node_paths_local import NodePathsLocal
from pants.contrib.node.tasks.node_task import NodeTask


class NodeInstall(NodeTask):
  """Installs a node_module target into the source directory"""

  @classmethod
  def prepare(cls, options, round_manager):
    super(NodeInstall, cls).prepare(options, round_manager)
    round_manager.require_data(NodePathsLocal)

  @classmethod
  def supports_passthru_args(cls):
    return True

  def execute(self):
    for target in self.context.target_roots:
      if self.is_node_module(target):
        node_paths = self.context.products.get_data(NodePathsLocal)
        self.context.log.debug('Start installing node_module target: {}'.format(target))
        self.context.log.debug('Node_path: {}'.format(node_paths.node_path(target)))
