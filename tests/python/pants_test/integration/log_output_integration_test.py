# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.testutil.pants_integration_test import PantsIntegrationTest


class LogOutputIntegrationTest(PantsIntegrationTest):
    def test_completed_log_output(self) -> None:
        sources = {
            "src/python/project/__init__.py": "",
            "src/python/project/lib.py": dedent(
                """\
                def add(x: int, y: int) -> int:
                    return x + y
                """
            ),
            "src/python/project/BUILD": "python_library()",
        }
        with self.setup_tmpdir(sources) as tmpdir:
            result = self.run_pants(
                [
                    "--no-dynamic-ui",
                    "--backend-packages=['pants.backend.python', 'pants.backend.python.typecheck.mypy']",
                    "-ldebug",
                    "typecheck",
                    f"{tmpdir}/src/python/project",
                ]
            )

        assert "[DEBUG] Starting: Run MyPy on" in result.stderr
        assert "[DEBUG] Completed: Run MyPy on" in result.stderr
