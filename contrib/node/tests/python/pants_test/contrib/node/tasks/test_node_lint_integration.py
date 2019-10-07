# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NodeLintIntegrationTest(PantsRunIntegrationTest):
    def test_lint_success(self):
        command = ["lint", "contrib/node/examples/src/node/hello::"]
        pants_run = self.run_pants(command=command)

        self.assert_success(pants_run)

    def test_lint_success_with_target_level_ignore(self):
        path = "contrib/node/examples/src/node/javascriptstyle-empty/index.js"
        content = "const console = require('console');\nconsole.log(\"Double Quotes\");\n"

        with self.temporary_file_content(path, content, binary_mode=False):
            command = ["lint", "contrib/node/examples/src/node/javascriptstyle-empty"]
            pants_run = self.run_pants(command=command)

            self.assert_success(pants_run)

    def test_lint_failure_without_target_level_ignore(self):
        path = "contrib/node/examples/src/node/javascriptstyle-empty/not_ignored_index.js"
        content = "const console = require('console');\nconsole.log(\"Double Quotes\");\n"

        with self.temporary_file_content(path, content, binary_mode=False):
            command = ["lint", "contrib/node/examples/src/node/javascriptstyle-empty"]
            pants_run = self.run_pants(command=command)

            self.assert_failure(pants_run)
