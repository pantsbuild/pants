# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.base.build_environment import get_buildroot
from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class RunnerIntegrationTest(PantsRunIntegrationTest):
    """Test logic performed in PantsRunner."""

    def test_warning_filter(self):
        # We load the testprojects pants-plugins to get some testing tasks and subsystems.
        cmdline = [
            "--no-pantsd",
            f"--pythonpath=+['{Path(get_buildroot(), 'testprojects/pants-plugins/src/python')}']",
            "--backend-packages=+['test_pants_plugin']",
            # This task will always emit a DeprecationWarning.
            "deprecation-warning",
        ]

        warning_run = self.run_pants(cmdline)
        self.assert_success(warning_run)
        self.assertRegex(
            warning_run.stderr_data,
            "\\[WARN\\].*DeprecationWarning: DEPRECATED: This is a test warning!",
        )

        non_warning_run = self.run_pants(
            cmdline,
            config={
                GLOBAL_SCOPE_CONFIG_SECTION: {
                    # NB: We do *not* include the exclamation point at the end, which tests that the regexps
                    # match from the beginning of the warning string, and don't require matching the entire
                    # string! We also lowercase the message to check that they are matched case-insensitively.
                    "ignore_pants_warnings": ["deprecated: this is a test warning"]
                },
            },
        )
        self.assert_success(non_warning_run)
        self.assertNotIn("test warning", non_warning_run.stderr_data)
