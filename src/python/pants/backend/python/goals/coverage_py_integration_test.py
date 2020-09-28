# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sqlite3
from pathlib import Path
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir

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


def run_coverage(tmpdir: str, *more_args: str) -> PantsResult:
    command = [
        "--backend-packages=pants.backend.python",
        "test",
        "--use-coverage",
        f"{tmpdir}/src/python/project:tests",
        f"{tmpdir}/tests/python/project_test:multiply",
        f"{tmpdir}/tests/python/project_test:arithmetic",
        f"{tmpdir}/tests/python/project_test/no_src",
        *more_args,
    ]
    result = run_pants(command)
    result.assert_success()
    # Regression test: make sure that individual tests do not complain about failing to
    # generate reports. This was showing up at test-time, even though the final merged
    # report would work properly.
    assert "Failed to generate report" not in result.stderr
    return result


def test_coverage() -> None:
    with setup_tmpdir(SOURCES) as tmpdir:
        result = run_coverage(tmpdir)
    assert (
        dedent(
            f"""\
            Name                                                          Stmts   Miss  Cover
            ---------------------------------------------------------------------------------
            {tmpdir}/src/python/project/__init__.py                        0      0   100%
            {tmpdir}/src/python/project/lib.py                             6      0   100%
            {tmpdir}/src/python/project/lib_test.py                        3      0   100%
            {tmpdir}/tests/python/project_test/__init__.py                 0      0   100%
            {tmpdir}/tests/python/project_test/no_src/__init__.py          0      0   100%
            {tmpdir}/tests/python/project_test/no_src/test_no_src.py       2      0   100%
            {tmpdir}/tests/python/project_test/test_arithmetic.py          3      0   100%
            {tmpdir}/tests/python/project_test/test_multiply.py            3      0   100%
            ---------------------------------------------------------------------------------
            TOTAL                                                            17      0   100%
            """
        )
        in result.stderr
    )


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

    assert "Wrote json coverage report to `dist/coverage/python`" in result.stderr_data
    json_coverage = coverage_path / "coverage.json"
    assert json_coverage.exists() is True
