# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class LogOutputIntegrationTest(PantsRunIntegrationTest):
    def _prepare_sources(self, tmpdir: str, build_root: str) -> Path:
        tmpdir_relative = Path(tmpdir).relative_to(build_root)
        src_root = Path(tmpdir, "src", "python", "project")
        src_root.mkdir(parents=True)
        (src_root / "__init__.py").touch()

        (src_root / "fake_test.py").write_text(
            dedent(
                """\

                def fake_test():
                    assert 1 == 2
                """
            )
        )

        (src_root / "BUILD").write_text(
            dedent(
                """\
                python_tests(
                    name="fake",
                    sources=["fake_test.py"],
                    dependencies=[],
                )
                """
            )
        )

        return tmpdir_relative

    def test_completed_log_output(self):
        build_root = get_buildroot()
        with temporary_dir(root_dir=build_root) as tmpdir:
            tmpdir_relative = self._prepare_sources(tmpdir, build_root)

            test_run_result = self.run_pants(
                ["--no-dynamic-ui", "test", f"{tmpdir_relative}/src/python/project:fake"]
            )

            assert "[INFO] Starting: Run Pytest for" in test_run_result.stderr_data
            assert "[INFO] Completed: Run Pytest for" in test_run_result.stderr_data
