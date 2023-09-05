# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import platform
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir

skip_on_linux_arm = pytest.mark.skipif(
    platform.system() == "Linux" and platform.machine() == "aarch64",
    reason="PyOxidizer is not supported on Linux ARM",
)


@skip_on_linux_arm
def test_end_to_end() -> None:
    """We test a couple edge cases:

    * Third-party dependencies can be used.
    * A `python_distribution` (implicitly) depending on another `python_distribution`.
    * `package` vs `run`
    """
    sources = {
        "hellotest/utils/greeter.py": "GREET = 'Hello world!'",
        "hellotest/utils/BUILD": dedent(
            """\
            python_sources(name="lib")

            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=python_artifact(name="utils-dist", version="0.0.1"),
            )
            """
        ),
        "hellotest/main.py": dedent(
            """\
            import colors
            import sys
            from hellotest.utils.greeter import GREET

            print(GREET)
            sys.exit(42)
            """
        ),
        "hellotest/BUILD": dedent(
            """\
            python_requirement(name="req", requirements=["ansicolors==1.1.8"])

            python_sources(name="lib")

            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=python_artifact(name="main-dist", version="0.0.1"),
            )

            pyoxidizer_binary(
                name="bin",
                entry_point="hellotest.main",
                dependencies=[":dist", "{tmpdir}/hellotest/utils:dist"],
            )
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        package_args = [
            "--backend-packages=['pants.backend.python', 'pants.backend.experimental.python.packaging.pyoxidizer']",
            "--python-interpreter-constraints=['>=3.8,<4']",
            f"--source-root-patterns=['/{tmpdir}']",
            "package",
            f"{tmpdir}/hellotest:bin",
        ]
        package_result = run_pants(package_args)
        package_result.assert_success()

        # Check that the binary is executable.
        bin_path = next(Path("dist", f"{tmpdir}.hellotest", "bin").glob("*/debug/install/bin"))
        bin_result = subprocess.run([bin_path], stdout=subprocess.PIPE)
        assert bin_result.returncode == 42
        assert bin_result.stdout == b"Hello world!\n"

        # Check that the binary runs.
        run_args = [
            "--backend-packages=['pants.backend.python', 'pants.backend.experimental.python.packaging.pyoxidizer']",
            "--python-interpreter-constraints=['>=3.8,<4']",
            f"--source-root-patterns=['/{tmpdir}']",
            "run",
            f"{tmpdir}/hellotest:bin",
        ]
        run_result = run_pants(run_args)
        print(run_result)
        assert run_result.exit_code == 42
        assert run_result.stdout == "Hello world!\n"


@skip_on_linux_arm
def test_requires_wheels() -> None:
    sources = {
        "hellotest/BUILD": dedent(
            """\
            python_distribution(
                name="dist",
                wheel=False,
                provides=python_artifact(name="dist", version="0.0.1"),
            )

            pyoxidizer_binary(name="bin", dependencies=[":dist"])
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=['pants.backend.python', 'pants.backend.experimental.python.packaging.pyoxidizer']",
            f"--source-root-patterns=['/{tmpdir}']",
            "package",
            f"{tmpdir}/hellotest:bin",
        ]
        result = run_pants(args)
        result.assert_failure()
        assert "InvalidTargetException" in result.stderr
