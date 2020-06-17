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

            # Set up the source files. Only `lib.py` will actually be tested, but we still expect
            # `random.py` to show up in the final report correctly.
            (src_root / "lib.py").write_text(
                dedent(
                    """\
                    def add(x, y):
                        return x + y

                    def subtract(x, y):
                        return x - y

                    def multiply(x, y):
                        return x * y
                    """
                )
            )
            (src_root / "random.py").write_text(
                dedent(
                    """\
                    def capitalize(s):
                        return s.capitalize()
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
            # These test that the `coverage` field works properly.
            test_root = Path(tmpdir, "tests", "python", "project_test")
            test_root.mkdir(parents=True)
            (test_root / "test_multiply.py").write_text(
                dedent(
                    """\
                    from project.lib import multiply

                    def test_multiply():
                        assert multiply(2, 3) == 6
                    """
                )
            )
            (test_root / "test_arithmetic.py").write_text(
                dedent(
                    """\
                    from project.lib import add, subtract

                    def test_arithmetic():
                        assert add(4, 3) == 7 == subtract(10, 3)
                    """
                )
            )
            (test_root / "BUILD").write_text(
                dedent(
                    f"""\
                    python_tests(
                      name="multiply",
                      sources=["test_multiply.py"],
                      dependencies=['{tmpdir_relative}/src/python/project'],
                      coverage=['project.lib'],
                    )

                    python_tests(
                      name="arithmetic",
                      sources=["test_arithmetic.py"],
                      dependencies=['{tmpdir_relative}/src/python/project'],
                      # This is a looser module than `project.lib`. We want to make sure we support
                      # this too.
                      coverage=['project'],
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
                    f"{tmpdir_relative}/tests/python/project_test:multiply",
                    f"{tmpdir_relative}/tests/python/project_test:arithmetic",
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
                Name                                         Stmts   Miss Branch BrPart  Cover
                ------------------------------------------------------------------------------
                {tmpdir_relative}/src/python/project/lib.py            6      0      0      0   100%
                {tmpdir_relative}/src/python/project/lib_test.py       3      0      0      0   100%
                {tmpdir_relative}/src/python/project/random.py         2      2      0      0     0%
                ------------------------------------------------------------------------------
                TOTAL                                           11      2      0      0    82%
                """
            )
            in result.stderr_data
        )
