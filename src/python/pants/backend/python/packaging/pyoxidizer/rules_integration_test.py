# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess
from pathlib import Path
from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_end_to_end() -> None:
    # TODO: Figure out how to handle interacting python_distribution targets, where dist1 depends
    #  on dist2.
    sources = {
        "hellotest/util.py": dedent(
            """\
            def greeting():
                return "hello world"
            """
        ),
        "hellotest/main.py": dedent(
            """\
            import colors

            print("hello world")
            """
        ),
        "hellotest/BUILD": dedent(
            """\
            python_requirement(name="req", requirements=["ansicolors==1.1.8"])

            python_sources(name="lib")

            python_distribution(
                name="dist1",
                dependencies=["./main.py:lib"],
                provides=python_artifact(name="dist1", version="0.0.1"),
            )

            python_distribution(
                name="dist2",
                dependencies=["./util.py:lib"],
                provides=python_artifact(name="dist2", version="0.0.1"),
            )

            pyoxidizer_binary(
                name="bin",
                entry_point="hellotest.main",
                dependencies=[":dist1", ":dist2"],
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
        bin_path = next(Path("dist", "build").glob("*/debug/install/bin"))
        bin_stdout = subprocess.run([bin_path], check=True, stdout=subprocess.PIPE).stdout
        assert bin_stdout == b"hello world\n"
