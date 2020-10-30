# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.bin.pants_loader import PantsLoader
from pants.testutil.pants_integration_test import run_pants


def test_invalid_locale() -> None:
    bypass_env = PantsLoader.ENCODING_IGNORE_ENV_VAR
    pants_run = run_pants(
        command=["help"], extra_env={"LC_ALL": "iNvALiD-lOcALe", "PYTHONUTF8": "0"}
    )
    pants_run.assert_failure()
    assert "Pants requires" in pants_run.stderr
    assert bypass_env in pants_run.stderr

    run_pants(
        command=["help"],
        extra_env={"LC_ALL": "iNvALiD-lOcALe", "PYTHONUTF8": "0", bypass_env: "1"},
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
    assert "entrypoint must be" in pants_run.stderr


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
