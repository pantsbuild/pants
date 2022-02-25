# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess
from pathlib import Path
from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_end_to_end() -> None:
    """We test a couple edge cases:

    * Third-party dependencies can be used.
    * A `python_distribution` (implicitly) depending on another `python_distribution`.
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
            from hellotest.utils.greeter import GREET

            print(GREET)
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
        args = [
            "--backend-packages=['pants.backend.python', 'pants.backend.experimental.python.packaging.pyoxidizer']",
            f"--source-root-patterns=['/{tmpdir}']",
            "package",
            f"{tmpdir}/hellotest:bin",
        ]
        result = run_pants(args)
        result.assert_success()

        # Check that the binary is executable.
        bin_path = next(Path("dist", f"{tmpdir}.hellotest", "bin").glob("*/debug/install/bin"))
        bin_stdout = subprocess.run([bin_path], check=True, stdout=subprocess.PIPE).stdout
        assert bin_stdout == b"Hello world!\n"


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
