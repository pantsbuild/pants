# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import time

import pytest

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_integration_test import ensure_daemon, run_pants, setup_tmpdir
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import fast_relpath, safe_file_dump
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase


@ensure_daemon
def test_goal_validation(use_pantsd: bool) -> None:
    result = run_pants(["blah", "::"], use_pantsd=use_pantsd)
    result.assert_failure()
    assert "Unknown goal: blah" in result.stdout


def test_unimplemented_goals_error() -> None:
    # Running on a Python target should fail if the backend is not activated.
    with setup_tmpdir(
        {"foo.py": "print('hello')", "BUILD": "python_source(source='foo.py')"}
    ) as tmpdir:
        result = run_pants(["run", tmpdir])
        result.assert_failure()
        assert "No relevant backends activate the `run` goal" in result.stderr
        run_pants(["--backend-packages=['pants.backend.python']", "run", tmpdir]).assert_success()


# Historically flaky: https://github.com/pantsbuild/pants/issues/10478
class TestGoalRuleIntegration(PantsDaemonIntegrationTestBase):
    hermetic = False

    def test_list_does_not_cache(self):
        with self.pantsd_successful_run_context() as ctx:

            def run_list():
                result = ctx.runner(["list", "testprojects/src/python/hello::"])
                ctx.checker.assert_started()
                return result

            first_run = run_list().stdout.splitlines()
            second_run = run_list().stdout.splitlines()
            self.assertTrue(sorted(first_run), sorted(second_run))

    def test_list_loop(self):
        # Create a BUILD file in a nested temporary directory, and add additional targets to it.
        with self.pantsd_test_context(log_level="info") as (
            workdir,
            config,
            checker,
        ), temporary_dir(root_dir=get_buildroot()) as tmpdir:
            rel_tmpdir = fast_relpath(tmpdir, get_buildroot())

            def dump(content):
                safe_file_dump(os.path.join(tmpdir, "BUILD"), content)

            # Dump an initial target before starting the loop.
            dump('target(name="one")')

            # Launch the loop as a background process.
            handle = self.run_pants_with_workdir_without_waiting(
                ["--loop", "--loop-max=3", "list", f"{tmpdir}:"], workdir=workdir, config=config
            )

            # Wait for pantsd to come up and for the loop to stabilize.
            checker.assert_started()
            time.sleep(10)

            # Replace the BUILD file content twice.
            dump('target(name="two")')
            time.sleep(10)
            dump('target(name="three")')

            # Verify that the three different target states were listed, and that the process exited.
            pants_result = handle.join()
            pants_result.assert_success()
            assert [
                f"{rel_tmpdir}:{name}" for name in ("one", "two", "three")
            ] == pants_result.stdout.splitlines()
