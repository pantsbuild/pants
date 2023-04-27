# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

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


def test_docker_run() -> None:
    sources = {
        "BUILD": "docker_image(name='run-image')",
        "Dockerfile": dedent(
            """\
            FROM alpine
            CMD echo "Hello from Docker image"
            """
        ),
    }
    result = run_pants_with_sources(
        sources,
        "run",
        "{tmpdir}:run-image",
    )

    print("pants stderr\n", result.stderr)
    assert "Hello from Docker image\n" == result.stdout
    result.assert_success()
