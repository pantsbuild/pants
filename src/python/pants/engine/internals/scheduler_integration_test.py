# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.testutil.pants_integration_test import PantsIntegrationTest, ensure_daemon
from pants.util.contextutil import temporary_dir


class SchedulerIntegrationTest(PantsIntegrationTest):
    def test_visualize_to(self):
        # Tests usage of the `--native-engine-visualize-to=` option, which triggers background
        # visualization of the graph. There are unit tests confirming the content of the rendered
        # results.
        with temporary_dir() as destdir:
            args = [
                f"--native-engine-visualize-to={destdir}",
                "--backend-packages=pants.backend.python",
                "list",
                "examples/src/python/example/hello/greet",
            ]
            self.run_pants(args).assert_success()
            destdir_files = list(Path(destdir).iterdir())
            self.assertTrue(len(destdir_files) > 0)

    @ensure_daemon
    def test_graceful_termination(self):
        args = [
            "--backend-packages=['pants.backend.python', 'internal_backend.rules_for_testing']",
            "list-and-die-for-testing",
            "examples/src/python/example/hello/greet",
        ]
        result = self.run_pants(args)
        result.assert_failure()
        self.assertEqual(result.stdout, "examples/src/python/example/hello/greet\n")
        self.assertEqual(result.exit_code, 42)
