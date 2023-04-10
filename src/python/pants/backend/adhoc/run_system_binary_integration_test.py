# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_system_binary_and_adhoc_tool() -> None:
    sources = {
        "src/test_file.txt": dedent(
            """\
            I am a duck.
            """
        ),
        "src/BUILD": dedent(
            """\
            files(name="files", sources=["*.txt",])

            system_binary(
                name="cat",
                binary_name="cat",
            )

            adhoc_tool(
                name="adhoc",
                runnable=":cat",
                execution_dependencies=[":files",],
                args=["test_file.txt",],
                log_output=True,
                stdout="stdout",
            )
            """
        ),
    }

    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=['pants.backend.experimental.adhoc',]",
            f"--source-root-patterns=['{tmpdir}/src']",
            "export-codegen",
            f"{tmpdir}/src:adhoc",
        ]
        result = run_pants(args)
        assert "[INFO] I am a duck." in result.stderr.strip()


@pytest.mark.parametrize(
    ("fingerprint,passes"),
    (
        (r"Binary Name v6\.32\.1", True),
        (r"(.*)v6\.(.*)", True),
        (r"Binary Name v6\.99999\.1", False),
    ),
)
def test_fingerprint(fingerprint: str, passes: bool) -> None:
    sources = {
        "src/BUILD": dedent(
            f"""\
            system_binary(
                name="bash",
                binary_name="bash",
                fingerprint=r"{fingerprint}",
                fingerprint_args=("-c", "echo Binary Name v6.32.1",),
            )

            adhoc_tool(
                name="adhoc",
                runnable=":bash",
                args=["-c","echo I am a duck!"],
                log_output=True,
                stdout="stdout",
            )
            """
        ),
    }

    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=['pants.backend.experimental.adhoc',]",
            f"--source-root-patterns=['{tmpdir}/src']",
            "export-codegen",
            f"{tmpdir}/src:adhoc",
        ]
        result = run_pants(args)
        if passes:
            assert result.exit_code == 0
            assert "[INFO] I am a duck!" in result.stderr.strip()
        else:
            assert result.exit_code != 0
            assert "Could not find a binary with name `bash`" in result.stderr.strip()


def test_runnable_dependencies() -> None:
    sources = {
        "src/BUILD": dedent(
            """\
            system_binary(
                name="bash",
                binary_name="bash",
            )

            system_binary(
                name="awk",
                binary_name="awk",
                fingerprint_args=["--version"],
                fingerprint=".*",
            )

            adhoc_tool(
                name="adhoc",
                runnable=":bash",
                runnable_dependencies=[":awk",],
                args=["-c", "awk 'BEGIN {{ print \\"I am a duck.\\" }}'"],
                log_output=True,
                stdout="stdout",
            )
            """
        ),
    }

    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=['pants.backend.experimental.adhoc',]",
            f"--source-root-patterns=['{tmpdir}/src']",
            "export-codegen",
            f"{tmpdir}/src:adhoc",
        ]
        result = run_pants(args)
        assert "[INFO] I am a duck." in result.stderr.strip()


def test_external_env_vars() -> None:
    sources = {
        "src/BUILD": dedent(
            """\

            system_binary(
                name="bash",
                binary_name="bash",
            )

            adhoc_tool(
                name="adhoc",
                runnable=":bash",
                args=["-c", "echo $ENVVAR"],
                log_output=True,
                stdout="stdout",
                extra_env_vars=["ENVVAR"],
            )
            """
        ),
    }

    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=['pants.backend.experimental.adhoc',]",
            f"--source-root-patterns=['{tmpdir}/src']",
            "export-codegen",
            f"{tmpdir}/src:adhoc",
        ]
        extra_env = {"ENVVAR": "clang"}
        result = run_pants(args, extra_env=extra_env)
        assert "[INFO] clang" in result.stderr.strip()
