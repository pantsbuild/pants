# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import PantsIntegrationTest


class ListIntegrationTest(PantsIntegrationTest):
    def test_list_all(self) -> None:
        pants_run = self.run_pants(["--backend-packages=pants.backend.python", "list", "::"])
        pants_run.assert_success()
        self.assertGreater(len(pants_run.stdout.strip().split()), 1)

    def test_list_none(self) -> None:
        pants_run = self.run_pants(["list"])
        pants_run.assert_success()
        self.assertIn("WARNING: No targets were matched in", pants_run.stderr)

    def test_list_invalid_dir(self) -> None:
        pants_run = self.run_pants(["list", "abcde::"])
        pants_run.assert_failure()
        self.assertIn("ResolveError", pants_run.stderr)

    def test_list_testproject(self) -> None:
        pants_run = self.run_pants(
            [
                "--backend-packages=pants.backend.python",
                "list",
                "testprojects/tests/python/pants/build_parsing::",
            ]
        )
        pants_run.assert_success()
        self.assertEqual(
            pants_run.stdout.strip(),
            "testprojects/tests/python/pants/build_parsing:test-nested-variable-access-in-function-call",
        )
