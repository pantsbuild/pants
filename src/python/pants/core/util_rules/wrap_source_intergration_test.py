# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_synthesized_python_is_included_in_package() -> None:
    sources = {
        "src/BUILD": dedent(
            """\
            shell_command(
                name="manufacture_python_code",
                tools=["touch",],
                command='echo print\\\\(\\\\"Hello, World!\\\\"\\\\) > hello_world.py',
                execution_dependencies=(),
                output_files=["hello_world.py",],
                workdir=".",
                root_output_directory="/",
            )

            experimental_wrap_as_python_sources(
                name="python_dependency",
                inputs=[":manufacture_python_code"],
            )

            pex_binary(
                name="app",
                dependencies=[":python_dependency"],
                entry_point=str(build_file_dir()).replace("/", ".") + ".hello_world",
            )
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=['pants.backend.python','pants.backend.shell']",
            f"--source-root-patterns=['/{tmpdir}/src']",
            "run",
            f"{tmpdir}/src:app",
        ]
        result = run_pants(args)
        result.assert_success()
        assert "Hello, World!" in result.stdout.strip()
