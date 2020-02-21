# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class NodeInstallIntegrationTest(PantsRunIntegrationTest):
    def test_node_install_with_prepublish(self):
        command = [
            "node-install",
            # Use same install parameters as resolve.node in .pants.d, I.E. don't generate a new yarn.lock file
            "--npm-resolver-force-option-override=True",
            "contrib/node/examples/src/node/server-project",
        ]
        pants_run = self.run_pants(command=command)
        self.assert_success(pants_run)

    def test_node_install_preinstalled_node_module_project(self):
        command = [
            "node-install",
            # Use same install parameters as resolve.node in .pants.d, I.E. don't generate a new yarn.lock file
            "--npm-resolver-force-option-override=True",
            "contrib/node/examples/src/node/preinstalled-project:unit",
        ]
        pants_run = self.run_pants(command=command)
        self.assert_success(pants_run)

    def test_node_install_yarn_workspaces(self):
        command = [
            "node-install",
            # Use same install parameters as resolve.node in .pants.d, I.E. don't generate a new yarn.lock file
            "--npm-resolver-force-option-override=True",
            "contrib/node/examples/src/node/yarn-workspaces",
        ]
        pants_run = self.run_pants(command=command)
        self.assert_success(pants_run)
