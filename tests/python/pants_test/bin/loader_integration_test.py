# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.bin.pants_loader import PantsLoader
from pants.testutil.pants_integration_test import PantsIntegrationTest


class LoaderIntegrationTest(PantsIntegrationTest):
    def test_invalid_locale(self):
        bypass_env = PantsLoader.ENCODING_IGNORE_ENV_VAR
        pants_run = self.run_pants(
            command=["help"], extra_env={"LC_ALL": "iNvALiD-lOcALe", "PYTHONUTF8": "0"}
        )
        pants_run.assert_failure()
        self.assertIn("Pants requires", pants_run.stderr)
        self.assertIn(bypass_env, pants_run.stderr)

        self.run_pants(
            command=["help"],
            extra_env={"LC_ALL": "iNvALiD-lOcALe", "PYTHONUTF8": "0", bypass_env: "1"},
        ).assert_success()

    def test_alternate_entrypoint(self):
        pants_run = self.run_pants(
            command=["help"], extra_env={"PANTS_ENTRYPOINT": "pants.bin.pants_exe:test"}
        )
        pants_run.assert_failure()
        self.assertIn("T E S T", pants_run.stdout)

    def test_alternate_entrypoint_bad(self):
        pants_run = self.run_pants(command=["help"], extra_env={"PANTS_ENTRYPOINT": "badness"})
        pants_run.assert_failure()
        self.assertIn("entrypoint must be", pants_run.stderr)

    def test_alternate_entrypoint_not_callable(self):
        pants_run = self.run_pants(
            command=["help"], extra_env={"PANTS_ENTRYPOINT": "pants.bin.pants_exe:TEST_STR"}
        )
        pants_run.assert_failure()
        self.assertIn("TEST_STR", pants_run.stderr)
        self.assertIn("not callable", pants_run.stderr)

    def test_alternate_entrypoint_scrubbing(self):
        pants_run = self.run_pants(
            command=["help"], extra_env={"PANTS_ENTRYPOINT": "pants.bin.pants_exe:test_env"}
        )
        pants_run.assert_success()
        self.assertIn("PANTS_ENTRYPOINT=None", pants_run.stdout)
