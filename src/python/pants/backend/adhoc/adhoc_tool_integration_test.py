# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_pex_binary() -> None:
    sources = {
        "src/hello.py": dedent(
            """\
            print("Hello, World!")
            """
        ),
        "src/BUILD": dedent(
            """\
            python_sources()

            pex_binary(
                name="pex",
                entry_point="hello.py",
            )

            adhoc_tool(
                name="adhoc",
                runnable=":pex",
            )
            """
        ),
    }

    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=['pants.backend.experimental.adhoc', 'pants.backend.python',]",
            f"--source-root-patterns=['{tmpdir}/src']",
            "export-codegen",
            f"{tmpdir}/src:adhoc",
        ]
        result = run_pants(args)
        assert result.exit_code == 0
