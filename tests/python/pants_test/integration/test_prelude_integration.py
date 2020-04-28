# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class PreludeIntegrationTest(PantsRunIntegrationTest):
    """Tests the functionality build file preludes."""

    def test_build_file_prelude(self):
        prelude = b"""def make_target():
    python_binary(name = "main", sources = ["main.py"])
"""
        build = b"make_target()"
        python = b"print('Unique output here!!')"

        with self.temporary_file_content("prelude", prelude), self.temporary_file_content(
            "BUILD", build
        ), self.temporary_file_content("main.py", python):
            run = self.run_pants(["--build-file-prelude-globs=prelude", "run", ":main"])
            self.assert_success(run)
            assert "Unique output here!!" in run.stdout_data
