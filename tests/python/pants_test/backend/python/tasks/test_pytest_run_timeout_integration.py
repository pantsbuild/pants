# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import time

import pytest

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


@pytest.mark.skip(reason="Is not working properly")
class PytestRunTimeoutIntegrationTest(PantsRunIntegrationTest):

    # NB: Occasionally running a test in CI may take multiple seconds. The tests in this file which
    # use the --timeout-default argument are not testing for performance regressions, but just for
    # correctness of timeout behavior, so we set this to a higher value to avoid flakiness.
    _non_flaky_timeout_seconds = 5

    def test_pytest_run_timeout_succeeds(self):
        pants_run = self.run_pants(
            [
                "test.pytest",
                f"--timeout-default={self._non_flaky_timeout_seconds}",
                "testprojects/tests/python/pants/timeout:exceeds_timeout",
                "--",
                "-kwithin_timeout",
            ]
        )
        self.assert_success(pants_run)

    def test_pytest_run_timeout_fails(self):
        start = time.time()
        pants_run = self.run_pants(
            [
                "test.pytest",
                "--coverage=auto",
                "--timeout-default=1",
                "--cache-ignore",
                "--chroot",
                "testprojects/tests/python/pants/timeout:exceeds_timeout",
                "--",
                "-kexceeds_timeout",
            ]
        )
        end = time.time()
        self.assert_failure(pants_run)

        # Ensure that the failure took less than 100 seconds to run to allow for test overhead.
        self.assertLess(end - start, 100)

        # Ensure that a warning about coverage reporting was emitted.
        self.assertIn(
            "No .coverage file was found! Skipping coverage reporting", pants_run.stdout_data
        )

        # Ensure that the timeout message triggered.
        self.assertIn("FAILURE: Timeout of 1 seconds reached.", pants_run.stdout_data)

    def test_pytest_run_timeout_cant_terminate(self):
        start = time.time()
        pants_run = self.run_pants(
            [
                "test.pytest",
                "--timeout-terminate-wait=2",
                f"--timeout-default={self._non_flaky_timeout_seconds}",
                "--coverage=auto",
                "--cache-ignore",
                "--chroot",
                "testprojects/tests/python/pants/timeout:ignores_terminate",
            ]
        )
        end = time.time()
        self.assert_failure(pants_run)

        # Ensure that the failure took less than 100 seconds to run to allow for test overhead.
        self.assertLess(end - start, 100)

        # Ensure that a warning about coverage reporting was emitted.
        self.assertIn(
            "No .coverage file was found! Skipping coverage reporting", pants_run.stdout_data
        )

        # Ensure that the timeout message triggered.
        self.assertIn("FAILURE: Timeout of 5 seconds reached.", pants_run.stdout_data)

        # Ensure that the warning about killing triggered.
        self.assertIn(
            "Timed out test did not terminate gracefully after 2 seconds, " "killing...",
            pants_run.stdout_data,
        )

    @pytest.mark.skip(reason="flaky: https://github.com/pantsbuild/pants/issues/9441")
    def test_pytest_run_killed_by_signal(self):
        start = time.time()
        pants_run = self.run_pants(
            [
                "test.pytest",
                "--timeout-terminate-wait=2",
                f"--timeout-default={self._non_flaky_timeout_seconds}",
                "--cache-ignore",
                "testprojects/tests/python/pants/timeout:terminates_self",
            ]
        )
        end = time.time()
        self.assert_failure(pants_run)

        # Ensure that the failure took less than 100 seconds to run to allow for test overhead.
        self.assertLess(end - start, 100)

        # Ensure that we get a message indicating the abnormal exit.
        self.assertIn("FAILURE: Test was killed by signal", pants_run.stdout_data)
