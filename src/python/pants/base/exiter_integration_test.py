# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import PantsIntegrationTest, ensure_daemon


class ExiterIntegrationTest(PantsIntegrationTest):
    """Tests that "interesting" exceptions are properly rendered."""

    @ensure_daemon
    def test_unicode_containing_exception(self):
        pants_run = self.run_pants(
            [
                "--backend-packages=pants.backend.python",
                "run",
                "testprojects/src/python/unicode/compilation_failure",
            ]
        )
        pants_run.assert_failure()
        self.assertIn("import sys¡", pants_run.stderr)
