# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_build_file_prelude() -> None:
    sources = {
        "prelude.py": dedent(
            """\
            def make_binary_macro():
                pex_binary(name="main", entry_point="main.py")
            """
        ),
        "BUILD": "python_sources()\nmake_binary_macro()",
        "main.py": "print('Hello world!')",
    }
    with setup_tmpdir(sources) as tmpdir:
        run = run_pants(
            [
                "--backend-packages=pants.backend.python",
                "--print-stacktrace",
                f"--build-file-prelude-globs={os.path.join(tmpdir, 'prelude.py')}",
                "run",
                f"{tmpdir}:main",
            ]
        )
    run.assert_success()
    assert "Hello world!" in run.stdout
