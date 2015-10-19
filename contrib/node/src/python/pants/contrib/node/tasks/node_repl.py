# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.repl_task_mixin import ReplTaskMixin
from pants.util.contextutil import pushd

from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_task import NodeTask


class NodeRepl(ReplTaskMixin, NodeTask):
  """Launches a Node.js REPL session."""

  @classmethod
  def prepare(cls, options, round_manager):
    super(NodeRepl, cls).prepare(options, round_manager)
    round_manager.require_data(NodePaths)

  @classmethod
  def select_targets(cls, target):
    return cls.is_node_module(target)

  @classmethod
  def supports_passthru_args(cls):
    return True

  def setup_repl_session(self, targets):
    # Return the path of the first product - the target on which "./pants repl was invoked"
    node_paths = self.context.products.get_data(NodePaths)
    return node_paths.node_path(targets[0])

  def launch_repl(self, node_path):
    args = self.get_passthru_args()
    node_repl = self.node_distribution.node_command(args=args)

    with pushd(node_path):
      repl_session = node_repl.run()
      repl_session.wait()
