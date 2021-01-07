# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir
from pants.util.dirutil import maybe_read_file


def test_workunits_logger() -> None:
    with setup_tmpdir({}) as tmpdir:
        dest = os.path.join(tmpdir, "dest.log")
        pants_run = run_pants(
            [
                "--backend-packages=+['workunit_logger','pants.backend.python']",
                f"--workunit-logger-dest={dest}",
                "list",
                "3rdparty::",
            ]
        )
        pants_run.assert_success()
        # Assert that the file was created and non-empty.
        assert maybe_read_file(dest)
