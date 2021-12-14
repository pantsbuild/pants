# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess
from textwrap import dedent

from pants.testutil._process_handler import SubprocessProcessHandler


def test_exit_1() -> None:
    process = subprocess.Popen(["/bin/sh", "-c", "exit 1"])
    process_handler = SubprocessProcessHandler(process)
    assert process_handler.wait() == 1


def test_exit_0() -> None:
    process = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    process_handler = SubprocessProcessHandler(process)
    assert process_handler.wait() == 0


def test_communicate_teeing_retrieves_stdout_and_stderr() -> None:
    process = subprocess.Popen(
        [
            "/bin/bash",
            "-c",
            """
            echo "1out"
            echo >&2 "1err"
            sleep 0.05
            echo >&2 "2err"
            echo "2out"
            sleep 0.05
            echo "3out"
            sleep 0.05
            echo >&2 "3err"
            sleep 0.05
            exit 1
            """,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process_handler = SubprocessProcessHandler(process)
    assert process_handler.communicate_teeing_stdout_and_stderr() == (
        dedent(
            """\
                1out
                2out
                3out
                """
        ).encode(),
        dedent(
            """\
                1err
                2err
                3err
                """
        ).encode(),
    )
    # Sadly, this test doesn't test that sys.std{out,err} also receive the output.
    # You can see it when you run it, but any way we have of spying on sys.std{out,err}
    # isn't pickleable enough to write a test which works.
