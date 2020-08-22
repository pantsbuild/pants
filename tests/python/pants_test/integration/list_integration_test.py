# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import PantsIntegrationTest


class ListIntegrationTest(PantsIntegrationTest):
    # TODO: Set hermetic=True after rewriting this test to stop using a testproject.
    hermetic = False

    def test_list_all(self) -> None:
        pants_run = self.run_pants(["list", "::"])
        self.assert_success(pants_run)
        self.assertGreater(len(pants_run.stdout.strip().split()), 1)

    def test_list_none(self) -> None:
        pants_run = self.run_pants(["list"])
        self.assert_success(pants_run)
        self.assertIn("WARNING: No targets were matched in", pants_run.stderr)

    def test_list_invalid_dir(self) -> None:
        pants_run = self.run_pants(["list", "abcde::"])
        self.assert_failure(pants_run)
        self.assertIn("ResolveError", pants_run.stderr)

    def test_list_testproject(self) -> None:
        pants_run = self.run_pants(["list", "testprojects/tests/python/pants/build_parsing::"])
        self.assert_success(pants_run)
        self.assertEqual(
            pants_run.stdout.strip(),
            "testprojects/tests/python/pants/build_parsing:test-nested-variable-access-in-function-call",
        )
