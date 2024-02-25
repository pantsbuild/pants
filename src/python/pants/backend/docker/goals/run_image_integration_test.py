# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir


def run_pants_with_sources(sources: dict[str, str], *args: str) -> PantsResult:
    with setup_tmpdir(sources) as tmpdir:
        return run_pants(
            [
                "--backend-packages=['pants.backend.docker']",
                "--python-interpreter-constraints=['>=3.7,<4']",
                "--pants-ignore=__pycache__",
            ]
            + [arg.format(tmpdir=tmpdir) for arg in args]
        )


@pytest.mark.parametrize("override_run_args", [True, False])
def test_docker_run(override_run_args) -> None:
    """This test exercises overriding the run args at the target level.

    It works by setting a default value for an envvar in the Dockerfile with the `ENV` statement,
    and then overriding that envvar with the `-e` option on the target level.
    """

    expected_value = "override" if override_run_args else "build"
    docker_run_args_attribute = 'run_args=["-e", "mykey=override"]' if override_run_args else ""

    sources = {
        "BUILD": f"docker_image(name='run-image', {docker_run_args_attribute})",
        "Dockerfile": dedent(
            """\
            FROM alpine
            ENV mykey=build
            CMD echo "Hello from Docker image with mykey=$mykey"
            """
        ),
    }

    result = run_pants_with_sources(
        sources,
        "run",
        "{tmpdir}:run-image",
    )
    print("pants stderr\n", result.stderr)
    assert f"Hello from Docker image with mykey={expected_value}\n" == result.stdout
    result.assert_success()
