# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import subprocess
import sys
import venv
from tempfile import TemporaryDirectory

import pytest

from pants.testutil.pants_integration_test import run_pants


@pytest.mark.platform_specific_behavior
def test_mypyc_build() -> None:
    dist_dir = "dist"
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    pants_run = run_pants(
        [
            "--backend-packages=['pants.backend.python','pants.backend.python.typecheck.mypy']",
            f"--python-interpreter-constraints=['=={pyver}']",
            "package",
            "testprojects/src/python/mypyc_fib:dist",
        ],
        extra_env={"PYTHON": sys.executable},
    )
    pants_run.assert_success()
    wheels = os.listdir(dist_dir)
    assert len(wheels) == 1
    wheel = os.path.join(dist_dir, wheels[0])

    with TemporaryDirectory() as venvdir:
        venv.create(venvdir, with_pip=True, clear=True, symlinks=True)
        subprocess.run([os.path.join(venvdir, "bin", "pip"), "install", wheel], check=True)
        proc = subprocess.run(
            [
                os.path.join(venvdir, "bin", "python"),
                "-c",
                "import mypyc_fib.fib",
            ],
            check=True,
            capture_output=True,
        )
        assert proc.stdout.splitlines(keepends=False)[0] == b"compiled"
