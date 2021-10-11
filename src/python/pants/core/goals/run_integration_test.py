# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import time
from pathlib import Path
from textwrap import dedent

from pants.testutil.pants_integration_test import (
    ensure_daemon,
    run_pants_with_workdir_without_waiting,
    temporary_workdir,
)


@ensure_daemon
def test_run_then_edit(use_pantsd: bool) -> None:
    slow = "slow.py"
    files = {
        slow: dedent(
            """\
        import time
        time.sleep(30)
        raise Exception("Should have been restarted by now!")
        """
        ),
        "BUILD": dedent(
            f"""\
        python_library(name='lib')
        pex_binary(name='bin', entry_point='{slow}', restartable=True)
        """
        ),
    }
    for name, content in files.items():
        Path(name).write_text(content)

    with temporary_workdir() as workdir:

        client_handle = run_pants_with_workdir_without_waiting(
            [
                "--backend-packages=['pants.backend.python']",
                "run",
                slow,
            ],
            workdir=workdir,
            use_pantsd=use_pantsd,
        )

        # The process shouldn't exit on its own.
        time.sleep(5)
        assert client_handle.process.poll() is None

        # Edit the file to restart the run, and check that it re-ran
        Path(slow).write_text('print("No longer slow!")')
        result = client_handle.join()
        result.assert_success()
        assert result.stdout == "No longer slow!\n"
