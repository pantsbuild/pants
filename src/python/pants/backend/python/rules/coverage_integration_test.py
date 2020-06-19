# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class CoverageIntegrationTest(PantsRunIntegrationTest):
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

            # Test that a `tests/` source root accurately gets coverage data for the `src/` root.
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
                    )

                    python_tests(
                      name="arithmetic",
                      sources=["test_arithmetic.py"],
                      dependencies=['{tmpdir_relative}/src/python/project'],
                    )
                    """
                )
            )

            # Test a file that does not cover any src code. While this is unlikely to happen, this
            # tests that we can properly handle the edge case. In particular, we want to make sure
            # that coverage still works when we omit this test file through the option
            # `--omit-test-sources`.
            no_src_folder = Path(tmpdir, "tests", "python", "project_test", "no_src")
            no_src_folder.mkdir()
            (no_src_folder / "test_no_src.py").write_text(
                "def test_true():\n\tassert True is True\n"
            )
            (no_src_folder / "BUILD").write_text("python_tests()")

            command = [
                "--no-v1",
                "--v2",
                "test",
                "--use-coverage",
                f"{tmpdir_relative}/src/python/project:tests",
                f"{tmpdir_relative}/tests/python/project_test:multiply",
                f"{tmpdir_relative}/tests/python/project_test:arithmetic",
                f"{tmpdir_relative}/tests/python/project_test/no_src",
            ]
            default_result = self.run_pants(command)
            omit_test_result = self.run_pants([*command, "--coverage-py-omit-test-sources"])
            filter_result = self.run_pants(
                [*command, "--coverage-py-filter=['project.lib', 'project_test.no_src']"]
            )

        for result in (default_result, omit_test_result, filter_result):
            assert result.returncode == 0
            # Regression test: make sure that individual tests do not complain about failing to
            # generate reports. This was showing up at test-time, even though the final merged
            # report would work properly.
            assert "Failed to generate report" not in result.stderr_data

        assert (
            dedent(
                f"""\
                Name                                                          Stmts   Miss Branch BrPart  Cover
                -----------------------------------------------------------------------------------------------
                {tmpdir_relative}/src/python/project/lib.py                             6      0      0      0   100%
                {tmpdir_relative}/src/python/project/lib_test.py                        3      0      0      0   100%
                {tmpdir_relative}/src/python/project/random.py                          2      2      0      0     0%
                {tmpdir_relative}/tests/python/project_test/no_src/test_no_src.py       2      0      0      0   100%
                {tmpdir_relative}/tests/python/project_test/test_arithmetic.py          3      0      0      0   100%
                {tmpdir_relative}/tests/python/project_test/test_multiply.py            3      0      0      0   100%
                -----------------------------------------------------------------------------------------------
                TOTAL                                                            19      2      0      0    89%
                """
            )
            in default_result.stderr_data
        )
        assert (
            dedent(
                f"""\
                Name                                       Stmts   Miss Branch BrPart  Cover
                ----------------------------------------------------------------------------
                {tmpdir_relative}/src/python/project/lib.py          6      0      0      0   100%
                {tmpdir_relative}/src/python/project/random.py       2      2      0      0     0%
                ----------------------------------------------------------------------------
                TOTAL                                          8      2      0      0    75%
                """
            )
            in omit_test_result.stderr_data
        )
        assert (
            dedent(
                f"""\
                Name                                                          Stmts   Miss Branch BrPart  Cover
                -----------------------------------------------------------------------------------------------
                {tmpdir_relative}/src/python/project/lib.py                             6      0      0      0   100%
                {tmpdir_relative}/tests/python/project_test/no_src/test_no_src.py       2      0      0      0   100%
                -----------------------------------------------------------------------------------------------
                TOTAL                                                             8      0      0      0   100%
                """
            )
            in filter_result.stderr_data
        )
