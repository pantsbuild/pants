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
    # These files must exist outside of a Pants `source_root` so that `coverage-py` doesn't try
    # to collect coverage metrics for them (as they are local to the chroot and coverage will
    # error unable to find their source)
    dirname = "not-a-source-root"
    files = {
        f"{dirname}/slow.py": dedent(
            """\
            import time
            time.sleep(30)
            raise Exception("Should have been restarted by now!")
            """
        ),
        f"{dirname}/BUILD": dedent(
            """\
            python_sources(name='lib')
            pex_binary(name='bin', entry_point='slow.py', restartable=True)
            """
        ),
    }
    Path(dirname).mkdir(exist_ok=True)
    for name, content in files.items():
        Path(name).write_text(content)

    with temporary_workdir() as workdir:
        client_handle = run_pants_with_workdir_without_waiting(
            [
                "--backend-packages=['pants.backend.python']",
                "run",
                f"{dirname}:bin",
            ],
            workdir=workdir,
            use_pantsd=use_pantsd,
        )

        # The process shouldn't exit on its own.
        time.sleep(5)
        assert client_handle.process.poll() is None

        # Edit the file to restart the run, and check that it re-ran
        Path(f"{dirname}/slow.py").write_text('print("No longer slow!")')
        result = client_handle.join()
        result.assert_success()
        assert result.stdout == "No longer slow!\n"
