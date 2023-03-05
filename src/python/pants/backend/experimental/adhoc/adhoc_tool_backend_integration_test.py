# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_adhoc_tool_is_loaded_by_backend() -> None:
    sources = {
        "src/floop.py": dedent(
            """\
            print("I'm Fleegan Floop!")
            """
        ),
        "src/BUILD": dedent(
            """\
            python_sources()

            adhoc_tool(
                name="adhoc",
                runnable="./floop.py",
                log_output=True,
                stdout="stdout",
            )

            archive(
                name="archive",
                format="tar",
                description="Package containing floop's stdout",
                files=[":adhoc",],
            )
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=['pants.backend.experimental.adhoc', 'pants.backend.python']",
            f"--source-root-patterns=['{tmpdir}/src']",
            "package",
            f"{tmpdir}/src:archive",
        ]
        result = run_pants(args)
        assert "[INFO] I'm Fleegan Floop!" in result.stderr.strip()
