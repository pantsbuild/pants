# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon
from pants.util.contextutil import temporary_dir


class SchedulerIntegrationTest(PantsRunIntegrationTest):
    def test_visualize_to(self):
        # Tests usage of the `--native-engine-visualize-to=` option, which triggers background
        # visualization of the graph. There are unit tests confirming the content of the rendered
        # results.
        with temporary_dir() as destdir:
            args = [
                f"--native-engine-visualize-to={destdir}",
                "list",
                "examples/src/scala/org/pantsbuild/example/hello/welcome",
            ]
            self.assert_success(self.run_pants(args))
            destdir_files = list(Path(destdir).iterdir())
            self.assertTrue(len(destdir_files) > 0)

    @ensure_daemon
    def test_graceful_termination(self):
        args = [
            "--no-v1",
            "--v2",
            "list-and-die-for-testing",
            "examples/src/scala/org/pantsbuild/example/hello/welcome",
        ]
        pants_result = self.run_pants(args)
        self.assert_failure(pants_result)
        self.assertEqual(
            pants_result.stdout_data,
            "examples/src/scala/org/pantsbuild/example/hello/welcome:welcome\n",
        )
        self.assertEqual(pants_result.returncode, 42)
