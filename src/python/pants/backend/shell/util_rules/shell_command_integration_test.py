# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_passthrough_args() -> None:
    sources = {
        "src/BUILD": dedent(
            """\
            run_shell_command(
                name="args-test",
                command='echo "cmd name (arg 0)=$0, args:$@"',
            )
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.shell",
            f"--source-root-patterns=['{tmpdir}/src']",
            "run",
            f"{tmpdir}/src:args-test",
            "--",
        ] + [f"arg{i}" for i in range(1, 4)]
        result = run_pants(args)
        assert "arg1 arg2 arg3" in result.stdout.strip()


def test_external_env_vars() -> None:
    sources = {
        "src/BUILD": dedent(
            """\
            shell_command(
                name="env-vars",
                command='echo $ENVVAR',
                extra_env_vars=["ENVVAR"],
                log_output=True,
            )
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.shell",
            f"--source-root-patterns=['{tmpdir}/src']",
            "export-codegen",
            f"{tmpdir}/src:env-vars",
        ]
        extra_env = {"ENVVAR": "clang"}
        result = run_pants(args, extra_env=extra_env)
        assert extra_env["ENVVAR"] in result.stderr
