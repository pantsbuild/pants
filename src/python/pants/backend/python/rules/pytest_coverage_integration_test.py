# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class PytestCoverageIntegrationTest(PantsRunIntegrationTest):
    def test_coverage(self) -> None:
        with temporary_dir(root_dir=get_buildroot()) as tmpdir:
            tmpdir_relative = Path(tmpdir).relative_to(get_buildroot())
            src_root = Path(tmpdir, "src", "python", "project")
            src_root.mkdir(parents=True)

            (src_root / "lib.py").write_text(
                dedent(
                    """\
                    def add(x, y):
                        return x + y


                    def multiply(x, y):
                        return x * y
                    """
                )
            )

            # Only test half of the library.
            (src_root / "lib_test.py").write_text(
                dedent(
                    """\
                    from project.lib import add

                    def test_add():
                        assert add(2, 3) == 5
                    """
                )
            )

            (src_root / "BUILD").write_text(
                dedent(
                    """\
                    python_library()

                    python_tests(
                      name="tests",
                      dependencies=[":project"],
                    )
                    """
                )
            )

            # Test the rest of the functionality in a different source root and different folder.
            # We only expect this to work because we explicitly set the `coverage` field.
            test_root = Path(tmpdir, "tests", "python", "project_test")
            test_root.mkdir(parents=True)
            (test_root / "test_lib_from_different_source_root.py").write_text(
                dedent(
                    """\
                    from project.lib import multiply

                    def test_multiply():
                        assert multiply(2, 3) == 6
                    """
                )
            )
            (test_root / "BUILD").write_text(
                dedent(
                    f"""\
                    python_tests(
                      dependencies=['{tmpdir_relative}/src/python/project'],
                      coverage=['project.lib'],
                    )
                    """
                )
            )

            result = self.run_pants(
                [
                    "--no-v1",
                    "--v2",
                    "test",
                    "--use-coverage",
                    f"{tmpdir_relative}/src/python/project:tests",
                    f"{tmpdir_relative}/tests/python/project_test",
                ]
            )

        assert result.returncode == 0
        # Regression test: make sure that individual tests do not complain about failing to
        # generate reports. This was showing up at test-time, even though the final merged report
        # would work properly.
        assert "Failed to generate report" not in result.stderr_data
        assert (
            dedent(
                f"""\
                Name                                                Stmts   Miss Branch BrPart  Cover
                -------------------------------------------------------------------------------------
                {tmpdir_relative}/src/python/project/lib.py                   4      1      0      0    100%
                {tmpdir_relative}/src/python/project/lib_test.py              3      0      0      0   100%
                -------------------------------------------------------------------------------------
                TOTAL                                                  10      1      0      0    100%
                """
            )
            in result.stderr_data
        )
