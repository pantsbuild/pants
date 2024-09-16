# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

import pytest

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_file_dump


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


def test_logging_binaries_skipped_due_to_error_exit() -> None:
    sources = {
        "src/BUILD": dedent(
            """\
        system_binary(
            name="grokker",
            binary_name="grokker",
        )

        system_binary(
            name="bash",
            binary_name="bash",
        )

        adhoc_tool(
            name="adhoc",
            runnable=":grokker",
            args=["-c", "grokker"],
            log_output=True,
            stdout="stdout",
            stderr="stderr",
        )
        """
        )
    }

    with setup_tmpdir(sources) as tmpdir, temporary_dir() as tmpdir_outside_buildroot:
        # Put the test binary outside of the buildroot.
        script_path = os.path.join(tmpdir_outside_buildroot, "grokker")
        safe_file_dump(
            script_path,
            dedent(
                """\
            #!/bin/bash
            echo "ERROR: This will always error." 1>&2
            exit 1
            """
            ),
            makedirs=True,
        )
        os.chmod(script_path, 0o555)

        args = [
            "--backend-packages=['pants.backend.experimental.adhoc',]",
            f"--source-root-patterns=['{tmpdir}/src']",
            f"--system-binaries-system-binary-paths=['{tmpdir_outside_buildroot}', '<PATH>']",
            "export-codegen",
            f"{tmpdir}/src:adhoc",
        ]
        result = run_pants(args)
        assert result.exit_code != 0
        assert "ERROR: This will always error." in result.stderr.strip()


def test_warn_when_candidate_binaries_fail() -> None:
    sources = {
        "src/BUILD": dedent(
            """\
        system_binary(
            name="bash",
            binary_name="bash",
        )

        system_binary(
            name="grokker-with-logging",
            binary_name="grokker",
            log_fingerprinting_errors=True,
        )

        system_binary(
            name="grokker-without-logging",
            binary_name="grokker",
            log_fingerprinting_errors=False,
        )

        adhoc_tool(
            name="adhoc-with-logging",
            runnable=":grokker-with-logging",
            args=["-c", "grokker"],
            log_output=True,
            stdout="stdout",
            stderr="stderr",
        )

        adhoc_tool(
            name="adhoc-without-logging",
            runnable=":grokker-without-logging",
            args=["-c", "grokker"],
            log_output=True,
            stdout="stdout",
            stderr="stderr",
        )
        """
        )
    }

    with setup_tmpdir(sources) as tmpdir, temporary_dir() as tmpdir_outside_buildroot:
        # Put the test binary outside of the buildroot.
        always_error_script_path = os.path.join(tmpdir_outside_buildroot, "subdir1", "grokker")
        safe_file_dump(
            always_error_script_path,
            dedent(
                """\
            #!/bin/bash
            echo "ERROR: This will always error." 1>&2
            exit 1
            """
            ),
            makedirs=True,
        )
        os.chmod(always_error_script_path, 0o555)

        always_succeeds_script_path = os.path.join(tmpdir_outside_buildroot, "subdir2", "grokker")
        safe_file_dump(
            always_succeeds_script_path,
            dedent(
                """\
            #!/bin/bash
            exit 0
            """
            ),
            makedirs=True,
        )
        os.chmod(always_succeeds_script_path, 0o555)

        base_args = [
            "--backend-packages=['pants.backend.experimental.adhoc',]",
            f"--source-root-patterns=['{tmpdir}/src']",
            f"--system-binaries-system-binary-paths=['{tmpdir_outside_buildroot}/subdir1', '{tmpdir_outside_buildroot}/subdir2', '<PATH>']",
            "export-codegen",
        ]

        result = run_pants(base_args + [f"{tmpdir}/src:adhoc-with-logging"])
        assert result.exit_code == 0
        assert "ERROR: This will always error." in result.stderr.strip()

        result = run_pants(base_args + [f"{tmpdir}/src:adhoc-without-logging"])
        assert result.exit_code == 0
        assert "ERROR: This will always error." not in result.stderr.strip()


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
