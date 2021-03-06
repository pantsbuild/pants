# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.pants_env_vars import IGNORE_UNRECOGNIZED_ENCODING, RECURSION_LIMIT
from pants.bin.pants_loader import PantsLoader
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


def test_alternate_entrypoint() -> None:
    pants_run = run_pants(
        command=["help"], extra_env={"PANTS_ENTRYPOINT": "pants.bin.pants_exe:test"}
    )
    pants_run.assert_success()
    assert "T E S T" in pants_run.stdout


def test_alternate_entrypoint_bad() -> None:
    pants_run = run_pants(command=["help"], extra_env={"PANTS_ENTRYPOINT": "badness"})
    pants_run.assert_failure()

    assert "must be of the form" in pants_run.stderr


def test_alternate_entrypoint_not_callable() -> None:
    pants_run = run_pants(
        command=["help"], extra_env={"PANTS_ENTRYPOINT": "pants.bin.pants_exe:TEST_STR"}
    )
    pants_run.assert_failure()
    assert "TEST_STR" in pants_run.stderr
    assert "not callable" in pants_run.stderr


def test_alternate_entrypoint_scrubbing() -> None:
    pants_run = run_pants(
        command=["help"], extra_env={"PANTS_ENTRYPOINT": "pants.bin.pants_exe:test_env"}
    )
    pants_run.assert_success()
    assert "PANTS_ENTRYPOINT=None" in pants_run.stdout


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
