# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.contrib.node.tasks.node_paths import NodePathsLocal
from pants.contrib.node.tasks.node_task import NodeTask


class NodeInstall(NodeTask):
  """Installs a node_module target into the directory that the target is defined in.

  Note:
    Running the node install on an example_project will install into the local source dir
    rather than in the typical .pants.d working directory.

    This task is intended to set up the environment for development purposes rather than
    to run tests or other isolated tasks.

  Example:
    ./pants node-install src/node/example_project:example_project

    This will produce a node_modules dir in `src/node/example_project/node_modules`
  """

  @classmethod
  def prepare(cls, options, round_manager):
    super().prepare(options, round_manager)
    round_manager.require_data(NodePathsLocal)

  def execute(self):
    for target in self.context.target_roots:
      if self.is_node_module(target):
        # By requiring NodePathsLocal, the node resolver walks through each node_module target and installs
        # them in topological order in the root source target path.
        node_paths = self.context.products.get_data(NodePathsLocal)
        self.context.log.debug('Start installing node_module target: {} in path'.format(target, node_paths.node_path(target)))
