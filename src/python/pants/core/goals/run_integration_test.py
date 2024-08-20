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
def test_restartable(use_pantsd: bool) -> None:
    # These files must exist outside of a Pants `source_root` so that `coverage-py` doesn't try
    # to collect coverage metrics for them (as they are local to the chroot and coverage will
    # error unable to find their source). We also need them to be in different locations for
    # each parametrization of this test.
    dirname = Path(f"test_restartable+{use_pantsd}/not-a-source-root").absolute()
    dirname.mkdir(parents=True)

    files = {
        dirname
        / "slow.py": dedent(
            """\
            import time
            time.sleep(30)
            raise Exception("Should have been restarted by now!")
            """
        ),
        dirname
        / "BUILD": dedent(
            """\
            python_sources(name='lib')
            pex_binary(name='bin', entry_point='slow.py', restartable=True)
            """
        ),
    }

    for path, content in files.items():
        path.write_text(content)

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
        (dirname / "slow.py").write_text('print("No longer slow!")')
        result = client_handle.join()
        result.assert_success()
        assert result.stdout == "No longer slow!\n"


@ensure_daemon
def test_non_restartable(use_pantsd: bool) -> None:
    # These files must exist outside of a Pants `source_root` so that `coverage-py` doesn't try
    # to collect coverage metrics for them (as they are local to the chroot and coverage will
    # error unable to find their source). We also need them to be in different locations for
    # each parametrization of this test.
    dirname = Path(f"test_non_restartable+{use_pantsd}/not-a-source-root").absolute()
    dirname.mkdir(parents=True)

    files = {
        dirname
        / "script.py": dedent(
            """\
            import os
            import time

            # Signal to the outside world that we've started.
            touch_path = os.path.join("{dirname}", "touch")
            with open(touch_path, "w") as fp:
                fp.write("")
            time.sleep(5)
            print("Not restarted")
            """.format(
                dirname=dirname
            )
        ),
        dirname
        / "BUILD": dedent(
            """\
            python_sources(name="src", restartable=False)
            """
        ),
    }

    for path, content in files.items():
        path.write_text(content)

    with temporary_workdir() as workdir:
        client_handle = run_pants_with_workdir_without_waiting(
            [
                "--backend-packages=['pants.backend.python']",
                "run",
                str(dirname / "script.py"),
            ],
            workdir=workdir,
            use_pantsd=use_pantsd,
        )

        # Check that the pants run has actually started.
        num_checks = 0
        touch_path = dirname / "touch"
        while not touch_path.exists():
            time.sleep(1)
            num_checks += 1
            if num_checks > 30:
                raise Exception("Failed to detect `pants run` process startup")

        (dirname / "script.py").write_text('print("Restarted")')
        result = client_handle.join()
        result.assert_success()
        assert result.stdout == "Not restarted\n"
