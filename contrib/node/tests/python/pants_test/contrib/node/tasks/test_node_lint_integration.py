# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import Iterator

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class NodeLintIntegrationTest(PantsRunIntegrationTest):

    EMPTY_DIRECTORY = Path("contrib/node/examples/src/node/javascriptstyle-empty")

    @contextmanager
    def setup_empty_directory_build_file(self) -> Iterator[None]:
        path = self.EMPTY_DIRECTORY / "BUILD"
        content = dedent(
            """\
            node_module(
              name='javascriptstyle-empty',
              sources=['package.json', 'yarn.lock', '**/*.js', '.eslintignore'],
              package_manager='yarn',
            )
            """
        )
        with self.temporary_file_content(str(path), content, binary_mode=False):
            yield

    def test_lint_success(self):
        command = ["lint", "contrib/node/examples/src/node/hello::"]
        pants_run = self.run_pants(command=command)
        self.assert_success(pants_run)

    def test_lint_success_with_target_level_ignore(self):
        path = self.EMPTY_DIRECTORY / "index.js"
        content = b"const console = require('console');\nconsole.log(\"Double Quotes\");\n"
        with self.setup_empty_directory_build_file(), self.temporary_file_content(
            str(path), content
        ):
            command = ["lint", str(self.EMPTY_DIRECTORY)]
            pants_run = self.run_pants(command=command)
            self.assert_success(pants_run)

    def test_lint_failure_without_target_level_ignore(self):
        path = self.EMPTY_DIRECTORY / "not_ignored_index.js"
        content = b"const console = require('console');\nconsole.log(\"Double Quotes\");\n"
        with self.setup_empty_directory_build_file(), self.temporary_file_content(
            str(path), content
        ):
            command = ["lint", str(self.EMPTY_DIRECTORY)]
            pants_run = self.run_pants(command=command)
            self.assert_failure(pants_run)
