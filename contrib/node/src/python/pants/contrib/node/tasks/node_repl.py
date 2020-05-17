# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os

from pants.base.exceptions import TaskError
from pants.task.repl_task_mixin import ReplTaskMixin
from pants.util.contextutil import pushd, temporary_dir

from pants.contrib.node.subsystems.package_managers import PACKAGE_MANAGER_NPM
from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_task import NodeTask


class NodeRepl(ReplTaskMixin, NodeTask):
    """Launches a Node.js REPL session."""

    SYNTHETIC_NODE_TARGET_NAME = "synthetic-node-repl-module"

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data(NodePaths)

    @classmethod
    def select_targets(cls, target):
        return cls.is_node_package(target)

    @classmethod
    def supports_passthru_args(cls):
        return True

    def setup_repl_session(self, targets):
        # Let MutexTaskMixin (base of ReplTaskMixin) do its normal filtering/validation logic on all
        # targets, but for NodeRepl we only want the subset in target_roots, since we don't need to
        # construct a classpath with transitive deps. NPM will install all the transitive deps
        # under the synthetic target we create below in launch_repl - we just need to put the
        # target_roots in the synthetic target's package.json dependencies.
        return [target for target in targets if target in self.context.target_roots]

    def launch_repl(self, targets):
        with temporary_dir() as temp_dir:
            node_paths = self.context.products.get_data(NodePaths)

            package_json_path = os.path.join(temp_dir, "package.json")
            package = {
                "name": self.SYNTHETIC_NODE_TARGET_NAME,
                "version": "0.0.0",
                "dependencies": {
                    target.package_name: node_paths.node_path(target)
                    if self.is_node_module(target)
                    else target.version
                    for target in targets
                },
            }
            with open(package_json_path, "w") as fp:
                json.dump(package, fp, indent=2)

            args = self.get_passthru_args()
            node_repl = self.node_distribution.node_command(
                args=args, node_paths=node_paths.all_node_paths if node_paths else None
            )

            with pushd(temp_dir):
                result, command = self.install_module(
                    package_manager=self.node_distribution.get_package_manager(
                        package_manager=PACKAGE_MANAGER_NPM
                    ),
                    workunit_name=self.SYNTHETIC_NODE_TARGET_NAME,
                )
                if result != 0:
                    raise TaskError(
                        "npm install of synthetic REPL module failed:\n"
                        "\t{} failed with exit code {}".format(command, result)
                    )

                repl_session = node_repl.run()
                repl_session.wait()
        # TODO(qsong): Issue #4278 Find a good way to preserve the flexibility of Node REPL
        # Repl task is hard to take over Node.js native REPL for the following reasons:
        # 1. Node.js can simply start from the package source root because node package is
        #   self-contained.
        # 2. There's no simple entry point (binary) for Node.js packages. A package may start from
        #   node, babel-node, babel-polyfill, webpack, etc.
        # In addition, since the repl task is modifying the package.json and there is no lockdown,
        # it is impossible to use yarnpkg to start repl unless the dependency resolver is removed.
