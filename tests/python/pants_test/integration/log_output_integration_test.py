# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_integration_test import PantsIntegrationTest
from pants.util.contextutil import temporary_dir


class LogOutputIntegrationTest(PantsIntegrationTest):
    def _prepare_sources(self, tmpdir: str, build_root: str) -> Path:
        tmpdir_relative = Path(tmpdir).relative_to(build_root)
        src_root = Path(tmpdir, "src", "python", "project")
        src_root.mkdir(parents=True)
        (src_root / "__init__.py").touch()
        (src_root / "lib.py").write_text(
            dedent(
                """\
                def add(x: int, y: int) -> int:
                    return x + y
                """
            )
        )
        (src_root / "BUILD").write_text("python_library()")
        return tmpdir_relative

    def test_completed_log_output(self) -> None:
        build_root = get_buildroot()
        with temporary_dir(root_dir=build_root) as tmpdir:
            tmpdir_relative = self._prepare_sources(tmpdir, build_root)

            test_run_result = self.run_pants(
                [
                    "--no-dynamic-ui",
                    "--backend-packages=['pants.backend.python', 'pants.backend.python.typecheck.mypy']",
                    "-ldebug",
                    "typecheck",
                    f"{tmpdir_relative}/src/python/project",
                ]
            )

            assert "[DEBUG] Starting: Run MyPy on" in test_run_result.stderr
            assert "[DEBUG] Completed: Run MyPy on" in test_run_result.stderr
