# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent

import pytest

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir
from pants.util.dirutil import safe_rmtree


@pytest.mark.platform_specific_behavior
def test_native_code() -> None:
    dist_dir = "dist"
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    pants_run = run_pants(
        [
            "--backend-packages=pants.backend.python",
            f"--python-interpreter-constraints=['=={pyver}']",
            "package",
            "testprojects/src/python/native:dist",
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
                "from native import name; print(name.get_name())",
            ],
            check=True,
            capture_output=True,
        )
        assert proc.stdout == b"Professor Native\n"


def package_determinism(expected_artifact_count: int, files: dict[str, str]) -> None:
    """Tests that the given sources can be `package`d reproducibly."""

    def digest(path: str) -> tuple[str, str]:
        d = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return path, d

    def run_and_digest(address: str) -> dict[str, str]:
        safe_rmtree("dist")
        pants_run = run_pants(
            [
                "--backend-packages=pants.backend.python",
                "--no-pantsd",
                "package",
                address,
            ],
        )
        pants_run.assert_success()
        return dict(digest(os.path.join("dist", f)) for f in os.listdir("dist"))

    with setup_tmpdir(files) as source_dir:
        one = run_and_digest(f"{source_dir}:dist")
        two = run_and_digest(f"{source_dir}:dist")

    assert len(one) == expected_artifact_count
    assert one == two


def test_deterministic_package_data() -> None:
    package_determinism(
        2,
        {
            "BUILD": dedent(
                """\
                python_distribution(
                    name="dist",
                    dependencies=["{tmpdir}/a", "{tmpdir}/b"],
                    provides=python_artifact(name="det", version="2.3.4"),
                )
                """
            ),
            "a/BUILD": dedent(
                """\
                python_sources(dependencies=[":resources"])
                resources(name="resources", sources=["*.txt"])
                """
            ),
            "a/source.py": "",
            "a/a.txt": "",
            "b/BUILD": dedent(
                """\
                python_sources(dependencies=[":resources"])
                resources(name="resources", sources=["*.txt"])
                """
            ),
            "b/source.py": "",
            "b/b.txt": "",
        },
    )


def test_output_path() -> None:
    dist_dir = "dist"
    output_path = os.path.join("nondefault", "output_dir")
    files = {
        "foo/BUILD": dedent(
            f"""\
            python_sources()

            python_distribution(
                name="dist",
                dependencies=[":foo"],
                provides=python_artifact(name="foo", version="2.3.4"),
                output_path="{output_path}"
            )
            """
        ),
        "foo/source.py": "",
    }
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    with setup_tmpdir(files) as source_dir:
        pants_run = run_pants(
            [
                "--backend-packages=pants.backend.python",
                f"--python-interpreter-constraints=['=={pyver}']",
                "package",
                f"{source_dir}/foo:dist",
            ],
            extra_env={"PYTHON": sys.executable},
        )
        pants_run.assert_success()
        dist_output_path = os.path.join(dist_dir, output_path)
        dist_entries = os.listdir(os.path.join(dist_dir, output_path))
        assert len(dist_entries) == 2
        for entry in dist_entries:
            assert os.path.isfile(os.path.join(dist_output_path, entry))
