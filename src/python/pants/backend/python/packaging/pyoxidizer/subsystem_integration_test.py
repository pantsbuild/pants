# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import run_pants


def test_subsystem_help_is_registered() -> None:
    pants_run = run_pants(
        [
            "--backend-packages=pants.backend.experimental.python.packaging.pyoxidizer",
            "help",
            "pyoxidizer",
        ]
    )
    pants_run.assert_success()
    assert "PANTS_PYOXIDIZER_ARGS" in pants_run.stdout
