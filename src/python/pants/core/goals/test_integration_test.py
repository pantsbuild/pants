# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir


def test_environment_usage() -> None:
    files = {
        "project/tests.py": dedent(
            """\
            def test_thing():
                pass
            """
        ),
        "project/BUILD": "python_tests(environment='python_38')",
        "BUILD": dedent(
            """\
            docker_environment(
                name="python_38",
                image="python:3.8",
                python_bootstrap_search_path=["<PATH>"],
            )
            """
        ),
    }

    with setup_tmpdir(files) as dirname:

        def run(*extra_test_args: str) -> PantsResult:
            return run_pants(
                [
                    "--backend-packages=['pants.backend.python']",
                    "--python-interpreter-constraints=['==3.8.*']",
                    f"--environments-preview-names={{'python_38': '{dirname}:python_38'}}",
                    "test",
                    *extra_test_args,
                    f"{dirname}/project:",
                ],
            )

        # A normal run should succeed.
        run().assert_success()

        # A debug run should fail (TODO: currently, see #17182).
        debug_run = run("--debug")
        debug_run.assert_failure()
        assert "Only local environments support running processes interactively" in debug_run.stderr
