# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from pathlib import Path

from pants.base.build_environment import get_buildroot
from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.testutil.pants_integration_test import run_pants


def test_warning_filter() -> None:
    # We load the testprojects pants-plugins to get some testing tasks and subsystems.
    cmdline = [
        "--no-pantsd",
        f"--pythonpath=+['{Path(get_buildroot(), 'testprojects/pants-plugins/src/python')}']",
        "--backend-packages=+['test_pants_plugin']",
        # This task will always emit a DeprecationWarning.
        "deprecation-warning",
    ]

    warning_run = run_pants(cmdline)
    warning_run.assert_success()
    assert bool(
        re.search(
            r"\[WARN\].*DeprecationWarning: DEPRECATED: This is a test warning!", warning_run.stderr
        )
    )

    non_warning_run = run_pants(
        cmdline,
        config={
            GLOBAL_SCOPE_CONFIG_SECTION: {
                # NB: We do *not* include the exclamation point at the end, which tests that the
                # regexps match from the beginning of the warning string, and don't require
                # matching the entire string!
                "ignore_pants_warnings": ["DEPRECATED: This is a test warning"]
            },
        },
    )
    non_warning_run.assert_success()
    assert "test warning" not in non_warning_run.stderr
