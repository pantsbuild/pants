# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sqlite3
from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.python.goals.coverage_py import CoverageSubsystem
from pants.base.build_environment import get_buildroot
from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions

SOURCES = {
    # Only `lib.py` will actually be tested, but we still expect `random.py` t`o show up in
    # the final report correctly.
    "src/python/project/__init__.py": "",
    "src/python/project/lib.py": dedent(
        """\
        def add(x, y):
            return x + y

        def subtract(x, y):
            return x - y

        def multiply(x, y):
            return x * y
        """
    ),
    # Include a type stub to ensure that we can handle it. We expect it to be ignored because the
    # test run does not use the file.
    "src/python/project/lib.pyi": dedent(
        """\
        def add(x: int, y: int) -> None:
            return x + y
        """
    ),
    "src/python/project/random.py": dedent(
        """\
        def capitalize(s):
            return s.capitalize()
        """
    ),
    # Only test half of the library.
    "src/python/project/lib_test.py": dedent(
        """\
        from project.lib import add

        def test_add():
            assert add(2, 3) == 5
        """
    ),
    "src/python/project/BUILD": dedent(
        """\
        python_library()

        python_tests(
            name="tests",
            dependencies=[":project"],
        )
        """
    ),
    "src/python/core/BUILD": "python_library()",
    "src/python/core/__init__.py": "",
    "src/python/core/untested.py": "CONSTANT = 42",
    "foo/bar.py": "BAZ = True",
    # Test that a `tests/` source root accurately gets coverage data for the `src/`
    # root.
    "tests/python/project_test/__init__.py": "",
    "tests/python/project_test/test_multiply.py": dedent(
        """\
        from project.lib import multiply

        def test_multiply():
            assert multiply(2, 3) == 6
        """
    ),
    "tests/python/project_test/test_arithmetic.py": dedent(
        """\
        from project.lib import add, subtract

        def test_arithmetic():
            assert add(4, 3) == 7 == subtract(10, 3)
        """
    ),
    "tests/python/project_test/BUILD": dedent(
        """\
        python_tests(
            name="multiply",
            sources=["test_multiply.py"],
            dependencies=['{tmpdir}/src/python/project'],
        )

        python_tests(
            name="arithmetic",
            sources=["test_arithmetic.py"],
            dependencies=['{tmpdir}/src/python/project'],
        )
        """
    ),
    # Test a file that does not cover any src code. While this is unlikely to happen,
    # this tests that we can properly handle the edge case.
    "tests/python/project_test/no_src/__init__.py": "",
    "tests/python/project_test/no_src/test_no_src.py": dedent(
        """\
        def test_true():
           assert True is True
        """
    ),
    "tests/python/project_test/no_src/BUILD.py": "python_tests()",
}


def run_coverage(tmpdir: str, *extra_args: str) -> PantsResult:
    command = [
        "--backend-packages=pants.backend.python",
        "test",
        "--use-coverage",
        f"{tmpdir}/src/python/project:tests",
        f"{tmpdir}/tests/python/project_test:multiply",
        f"{tmpdir}/tests/python/project_test:arithmetic",
        f"{tmpdir}/tests/python/project_test/no_src",
        f"--source-root-patterns=['/{tmpdir}/src/python', '{tmpdir}/tests/python', '{tmpdir}/foo']",
        *extra_args,
    ]
    result = run_pants(command)
    result.assert_success()
    # Regression test: make sure that individual tests do not complain about failing to
    # generate reports. This was showing up at test-time, even though the final merged
    # report would work properly.
    assert "Failed to generate report" not in result.stderr
    return result


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(CoverageSubsystem.default_interpreter_constraints),
)
def test_coverage(major_minor_interpreter: str) -> None:
    with setup_tmpdir(SOURCES) as tmpdir:
        result = run_coverage(
            tmpdir, f"--coverage-py-interpreter-constraints=['=={major_minor_interpreter}.*']"
        )
    assert (
        dedent(
            f"""\
            Name                                                          Stmts   Miss  Cover
            ---------------------------------------------------------------------------------
            {tmpdir}/src/python/project/__init__.py                        0      0   100%
            {tmpdir}/src/python/project/lib.py                             6      0   100%
            {tmpdir}/src/python/project/lib_test.py                        3      0   100%
            {tmpdir}/src/python/project/random.py                          2      2     0%
            {tmpdir}/tests/python/project_test/__init__.py                 0      0   100%
            {tmpdir}/tests/python/project_test/no_src/__init__.py          0      0   100%
            {tmpdir}/tests/python/project_test/no_src/test_no_src.py       2      0   100%
            {tmpdir}/tests/python/project_test/test_arithmetic.py          3      0   100%
            {tmpdir}/tests/python/project_test/test_multiply.py            3      0   100%
            ---------------------------------------------------------------------------------
            TOTAL                                                            19      2    89%
            """
        )
        in result.stderr
    )


def test_coverage_global() -> None:
    with setup_tmpdir(SOURCES) as tmpdir:
        result = run_coverage(tmpdir, "--coverage-py-global-report")
    assert (
        dedent(
            f"""\
            Name                                                          Stmts   Miss  Cover
            ---------------------------------------------------------------------------------
            {tmpdir}/foo/bar.py                                            1      1     0%
            {tmpdir}/src/python/core/__init__.py                           0      0   100%
            {tmpdir}/src/python/core/untested.py                           1      1     0%
            {tmpdir}/src/python/project/__init__.py                        0      0   100%
            {tmpdir}/src/python/project/lib.py                             6      0   100%
            {tmpdir}/src/python/project/lib_test.py                        3      0   100%
            {tmpdir}/src/python/project/random.py                          2      2     0%
            {tmpdir}/tests/python/project_test/__init__.py                 0      0   100%
            {tmpdir}/tests/python/project_test/no_src/BUILD.py             1      1     0%
            {tmpdir}/tests/python/project_test/no_src/__init__.py          0      0   100%
            {tmpdir}/tests/python/project_test/no_src/test_no_src.py       2      0   100%
            {tmpdir}/tests/python/project_test/test_arithmetic.py          3      0   100%
            {tmpdir}/tests/python/project_test/test_multiply.py            3      0   100%
            ---------------------------------------------------------------------------------
            TOTAL                                                            22      5    77%
            """
        )
        in result.stderr
    ), result.stderr


def test_coverage_with_filter() -> None:
    with setup_tmpdir(SOURCES) as tmpdir:
        result = run_coverage(tmpdir, "--coverage-py-filter=['project.lib', 'project_test.no_src']")
    assert (
        dedent(
            f"""\
            Name                                                          Stmts   Miss  Cover
            ---------------------------------------------------------------------------------
            {tmpdir}/src/python/project/lib.py                             6      0   100%
            {tmpdir}/tests/python/project_test/no_src/__init__.py          0      0   100%
            {tmpdir}/tests/python/project_test/no_src/test_no_src.py       2      0   100%
            ---------------------------------------------------------------------------------
            TOTAL                                                             8      0   100%
            """
        )
        in result.stderr
    )


def test_coverage_raw() -> None:
    with setup_tmpdir(SOURCES) as tmpdir:
        result = run_coverage(tmpdir, "--coverage-py-report=raw")
    assert "Wrote raw coverage report to `dist/coverage/python`" in result.stderr
    coverage_data = Path(get_buildroot(), "dist", "coverage", "python", ".coverage")
    assert coverage_data.exists() is True
    conn = sqlite3.connect(coverage_data.as_posix())
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    assert {row[0] for row in cursor.fetchall()} == {
        "arc",
        "context",
        "coverage_schema",
        "file",
        "line_bits",
        "meta",
        "tracer",
    }


def test_coverage_html_xml_json() -> None:
    with setup_tmpdir(SOURCES) as tmpdir:
        result = run_coverage(tmpdir, "--coverage-py-report=['xml', 'html', 'json']")
    coverage_path = Path(get_buildroot(), "dist", "coverage", "python")
    assert coverage_path.exists() is True

    assert "Wrote xml coverage report to `dist/coverage/python`" in result.stderr
    xml_coverage = coverage_path / "coverage.xml"
    assert xml_coverage.exists() is True

    assert "Wrote html coverage report to `dist/coverage/python`" in result.stderr
    html_cov_dir = coverage_path / "htmlcov"
    assert html_cov_dir.exists() is True
    assert (html_cov_dir / "index.html").exists() is True

    assert "Wrote json coverage report to `dist/coverage/python`" in result.stderr
    json_coverage = coverage_path / "coverage.json"
    assert json_coverage.exists() is True


def test_default_coverage_issues_12390() -> None:
    # N.B.: This ~replicates the repo used to reproduce this issue at
    # https://github.com/alexey-tereshenkov-oxb/monorepo-coverage-pants.
    files = {
        "requirements.txt": "PySide2==5.15.2",
        "BUILD": dedent(
            """\
            python_requirements(
                module_mapping={{
                    "PySide2": ["PySide2"],
                }},
            )
            """
        ),
        "minimalcov/minimalcov/src/foo.py": 'print("In the foo module!")',
        "minimalcov/minimalcov/src/BUILD": "python_library()",
        "minimalcov/minimalcov/tests/test_foo.py": dedent(
            """\
            import minimalcov.src.foo

            from PySide2.QtWidgets import QApplication

            def test_1():
                assert True
            """
        ),
        "minimalcov/minimalcov/tests/BUILD": "python_tests()",
    }
    with setup_tmpdir(files) as tmpdir:
        command = [
            "--backend-packages=pants.backend.python",
            "test",
            "--use-coverage",
            "::",
            f"--source-root-patterns=['/{tmpdir}/minimalcov']",
            "--coverage-py-report=raw",
        ]
        result = run_pants(command)
        result.assert_success()

    assert (
        dedent(
            f"""\
            Name                                                  Stmts   Miss  Cover
            -------------------------------------------------------------------------
            {tmpdir}/minimalcov/minimalcov/src/foo.py              1      0   100%
            {tmpdir}/minimalcov/minimalcov/tests/test_foo.py       4      0   100%
            -------------------------------------------------------------------------
            TOTAL                                                     5      0   100%
            """
        )
        in result.stderr
    ), result.stderr
