# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import ensure_daemon, run_pants


@ensure_daemon
def test_unicode_containing_exception():
    pants_run = run_pants(
        [
            "--backend-packages=pants.backend.python",
            "run",
            "testprojects/src/python/unicode/compilation_failure",
        ]
    )
    pants_run.assert_failure()
    assert "import sys¡" in pants_run.stderr
