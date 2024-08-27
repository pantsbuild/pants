# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import run_pants


def test_auxiliary_goal_invocation() -> None:
    result1 = run_pants(
        [
            "experimental-bsp",
        ]
    )
    result1.assert_failure()
    assert "Unknown goal: experimental-bsp" in result1.stdout

    result2 = run_pants(
        [
            "--backend-packages=pants.backend.experimental.bsp",
            "experimental-bsp",
        ]
    )
    result2.assert_success()
    assert "Wrote BSP runner script" in result2.stderr
    assert "Wrote BSP connection file" in result2.stderr
