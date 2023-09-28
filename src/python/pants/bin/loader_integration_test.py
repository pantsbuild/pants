# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.bin.pants_env_vars import (
    DAEMON_ENTRYPOINT,
    IGNORE_UNRECOGNIZED_ENCODING,
    RECURSION_LIMIT,
)
from pants.testutil.pants_integration_test import PantsResult, run_pants


def test_invalid_locale() -> None:
    pants_run = run_pants(
        command=["help"], extra_env={"LC_ALL": "iNvALiD-lOcALe", "PYTHONUTF8": "0"}
    )

    pants_run.assert_failure()
    assert "Pants requires" in pants_run.stderr
    assert IGNORE_UNRECOGNIZED_ENCODING in pants_run.stderr
    run_pants(
        command=["help"],
        extra_env={
            "LC_ALL": "iNvALiD-lOcALe",
            "PYTHONUTF8": "0",
            IGNORE_UNRECOGNIZED_ENCODING: "1",
        },
    ).assert_success()


TEST_STR = "T E S T"


def exercise_alternate_entrypoint() -> None:
    print(TEST_STR)


def test_alternate_entrypoint() -> None:
    pants_run = run_pants(
        command=["help"],
        extra_env={
            DAEMON_ENTRYPOINT: "pants.bin.loader_integration_test:exercise_alternate_entrypoint"
        },
    )
    pants_run.assert_success()
    assert "T E S T" in pants_run.stdout


def test_alternate_entrypoint_bad() -> None:
    pants_run = run_pants(command=["help"], extra_env={DAEMON_ENTRYPOINT: "badness"})
    pants_run.assert_failure()

    assert "must be of the form" in pants_run.stderr


def exercise_alternate_entrypoint_scrubbing():
    """An alternate test entrypoint for exercising scrubbing."""
    print(f"{DAEMON_ENTRYPOINT}={os.environ.get(DAEMON_ENTRYPOINT)}")


def test_alternate_entrypoint_scrubbing() -> None:
    pants_run = run_pants(
        command=["help"],
        extra_env={
            DAEMON_ENTRYPOINT: "pants.bin.loader_integration_test:exercise_alternate_entrypoint_scrubbing"
        },
    )
    pants_run.assert_success()
    assert f"{DAEMON_ENTRYPOINT}=None" in pants_run.stdout


def test_recursion_limit() -> None:
    def run(limit: str) -> PantsResult:
        return run_pants(command=["help"], extra_env={RECURSION_LIMIT: limit})

    # Large value succeeds.
    run("100000").assert_success()
    # Very small value fails in an arbitrary spot.
    small_run = run("1")
    small_run.assert_failure()
    assert "RecursionError" in small_run.stderr
    # Non integer value fails.
    run("this isn't an int").assert_failure()


def test_non_utf8_env_vars() -> None:
    res = run_pants(
        command=["--version"],
        extra_env={
            "FOO": b"B\xa5R",
            b"F\xa5O": "BAR",
        },
        use_pantsd=True,
    )
    print(res.stdout)
    res.assert_success()
