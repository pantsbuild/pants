# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.bin.pants_loader import PantsLoader
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class LoaderIntegrationTest(PantsRunIntegrationTest):
    def test_invalid_locale(self):
        bypass_env = PantsLoader.ENCODING_IGNORE_ENV_VAR
        pants_run = self.run_pants(
            command=["help"], extra_env={"LC_ALL": "iNvALiD-lOcALe", "PYTHONUTF8": "0"}
        )
        self.assert_failure(pants_run)
        self.assertIn("Pants requires", pants_run.stderr_data)
        self.assertIn(bypass_env, pants_run.stderr_data)

        pants_run = self.run_pants(
            command=["help"],
            extra_env={"LC_ALL": "iNvALiD-lOcALe", "PYTHONUTF8": "0", bypass_env: "1"},
        )
        self.assert_success(pants_run)

    def test_alternate_entrypoint(self):
        pants_run = self.run_pants(
            command=["help"], extra_env={"PANTS_ENTRYPOINT": "pants.bin.pants_exe:test"}
        )
        self.assert_success(pants_run)
        self.assertIn("T E S T", pants_run.stdout_data)

    def test_alternate_entrypoint_bad(self):
        pants_run = self.run_pants(command=["help"], extra_env={"PANTS_ENTRYPOINT": "badness"})
        self.assert_failure(pants_run)
        self.assertIn("entrypoint must be", pants_run.stderr_data)

    def test_alternate_entrypoint_not_callable(self):
        pants_run = self.run_pants(
            command=["help"], extra_env={"PANTS_ENTRYPOINT": "pants.bin.pants_exe:TEST_STR"}
        )
        self.assert_failure(pants_run)
        self.assertIn("TEST_STR", pants_run.stderr_data)
        self.assertIn("not callable", pants_run.stderr_data)

    def test_alternate_entrypoint_scrubbing(self):
        pants_run = self.run_pants(
            command=["help"], extra_env={"PANTS_ENTRYPOINT": "pants.bin.pants_exe:test_env"}
        )
        self.assert_success(pants_run)
        self.assertIn("PANTS_ENTRYPOINT=None", pants_run.stdout_data)
