# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_run_script_from_3rdparty_dist_issue_13747() -> None:
    sources = {
        "src/BUILD": dedent(
            """\
            python_requirement(name="cowsay", requirements=["cowsay==4.0"])
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        SAY = "moooo"
        args = [
            "--backend-packages=pants.backend.python",
            f"--source-root-patterns=['/{tmpdir}/src']",
            "run",
            f"{tmpdir}/src:cowsay",
            "--",
            SAY,
        ]
        result = run_pants(args)
        result.assert_success()
        assert SAY in result.stdout.strip()
