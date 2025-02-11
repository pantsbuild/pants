# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.sql.lint.sqlfluff import rules as sqlfluff_rules
from pants.backend.sql.lint.sqlfluff import skip_field
from pants.backend.sql.lint.sqlfluff import subsystem as sqlfluff_subsystem
from pants.backend.sql.lint.sqlfluff.rules import (
    SqlfluffFixRequest,
    SqlfluffFormatRequest,
    SqlfluffLintRequest,
)
from pants.backend.sql.target_types import SqlSourcesGeneratorTarget
from pants.core.goals.fix import FixResult
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult
from pants.core.util_rules import config_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir
from pants.testutil.rule_runner import QueryRule, RuleRunner

GOOD_FILE = dedent(
    """\
    select
        e.id,
        e.name
    from employees as e
    """
)
BAD_FILE = dedent(
    """\
    select
        e.id,
        name
    from employees as e
    """
)
UNFORMATTED_FILE = dedent(
    """\
    select e.id, e.name
    from employees as e
    """
)
CONFIG_POSTGRES = dedent(
    """\
    [sqlfluff]
    dialect = postgres
    """
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *skip_field.rules(),
            *sqlfluff_subsystem.rules(),
            *config_files.rules(),
            *sqlfluff_rules.rules(),
            QueryRule(FixResult, [SqlfluffFixRequest.Batch]),
            QueryRule(LintResult, [SqlfluffLintRequest.Batch]),
            QueryRule(FmtResult, [SqlfluffFormatRequest.Batch]),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[SqlSourcesGeneratorTarget],
    )


def run_sqlfluff(
    rule_runner: RuleRunner,
    paths: list[str],
    files: dict[str, str],
    *,
    extra_args: list[str] | None = None,
) -> tuple[PantsResult, PantsResult, PantsResult]:
    args = [
        "--backend-packages=['pants.backend.experimental.sql','pants.backend.experimental.sql.lint.sqlfluff']",
        "--no-watch-filesystem",
        "--no-pantsd",
        '--sqlfluff-fix-args="--force"',
        *(extra_args or ()),
    ]

    with setup_tmpdir(files) as workdir:
        result = run_pants(command=[*args, "list", f"{workdir}/::"])
        result.assert_success()
        assert result.stdout == "abc"

        addresses = [f"{workdir}/{path}" for path in paths]
        fix_result = run_pants(command=[*args, "fix", *addresses])
        lint_result = run_pants(command=[*args, "lint", *addresses])
        fmt_result = run_pants(command=[*args, "fmt", *addresses])
    return fix_result, lint_result, fmt_result


def collect_files(rootdir: str) -> dict:
    result = {}
    for root, _, files in os.walk(rootdir):
        for file in files:
            path = f"{root}/{file}"
            relpath = os.path.relpath(path, rootdir)
            result[relpath] = Path(path).read_text()
    return result


@pytest.fixture
def args():
    return [
        "--backend-packages=['pants.backend.experimental.sql','pants.backend.experimental.sql.lint.sqlfluff']",
        '--sqlfluff-fix-args="--force"',
        "--python-interpreter-constraints=['==3.12.*']",
    ]


@pytest.fixture
def good_query():
    return {
        "project/query.sql": GOOD_FILE,
        "project/BUILD": "sql_sources()",
        "project/.sqlfluff": CONFIG_POSTGRES,
    }


def test_passing_lint(good_query: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(good_query) as tmpdir:
        result = run_pants([*args, "lint", f"{tmpdir}/project:"])
    result.assert_success()


def test_passing_fix(good_query: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(good_query) as tmpdir:
        result = run_pants([*args, "fix", f"{tmpdir}/project:"])
        files = collect_files(tmpdir)
    result.assert_success()
    assert result.stdout == ""
    assert "sqlfluff format made no changes." in result.stderr
    assert "sqlfluff made no changes." in result.stderr
    assert files["project/query.sql"] == GOOD_FILE


def test_passing_fmt(good_query: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(good_query) as tmpdir:
        result = run_pants([*args, "fmt", f"{tmpdir}/project:"])
        files = collect_files(tmpdir)
    result.assert_success()
    assert result.stdout == ""
    assert "sqlfluff format made no changes." in result.stderr
    assert files["project/query.sql"] == GOOD_FILE


@pytest.fixture
def bad_query():
    return {
        "project/query.sql": BAD_FILE,
        "project/BUILD": "sql_sources()",
        "project/.sqlfluff": CONFIG_POSTGRES,
    }


def test_failing_lint(bad_query: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(bad_query) as tmpdir:
        result = run_pants([*args, "lint", f"{tmpdir}/project:"])
    result.assert_failure()
    assert (
        dedent(
            f"""\
    == [{tmpdir}/project/query.sql] FAIL
    L:   3 | P:   5 | RF03 | Unqualified reference 'name' found in single table
                           | select. [references.consistent]
    L:   3 | P:   5 | RF03 | Unqualified reference 'name' found in single table
                           | select which is inconsistent with previous references.
                           | [references.consistent]
    All Finished!
    """
        )
        in result.stderr
    )


def test_failing_fix(bad_query: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(bad_query) as tmpdir:
        result = run_pants([*args, "fix", f"{tmpdir}/project:"])
        files = collect_files(tmpdir)
    result.assert_success()
    assert "sqlfluff made changes." in result.stderr
    assert files["project/query.sql"] == GOOD_FILE


def test_failing_fmt(bad_query: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(bad_query) as tmpdir:
        result = run_pants([*args, "fmt", f"{tmpdir}/project:"])
        files = collect_files(tmpdir)
    result.assert_success()
    assert "sqlfluff format made no changes." in result.stderr
    assert files["project/query.sql"] == BAD_FILE


@pytest.fixture
def multiple_queries() -> dict[str, str]:
    return {
        "project/good.sql": GOOD_FILE,
        "project/bad.sql": BAD_FILE,
        "project/unformatted.sql": UNFORMATTED_FILE,
        "project/BUILD": "sql_sources(name='t')",
        "project/.sqlfluff": CONFIG_POSTGRES,
    }


def test_multiple_targets_lint(multiple_queries: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(multiple_queries) as tmpdir:
        result = run_pants([*args, "lint", f"{tmpdir}/project:"])
    result.assert_failure()
    assert (
        dedent(
            f"""\
            == [{tmpdir}/project/bad.sql] FAIL
            L:   3 | P:   5 | RF03 | Unqualified reference 'name' found in single table
                                   | select. [references.consistent]
            L:   3 | P:   5 | RF03 | Unqualified reference 'name' found in single table
                                   | select which is inconsistent with previous references.
                                   | [references.consistent]
            == [{tmpdir}/project/unformatted.sql] FAIL
            L:   1 | P:   1 | LT09 | Select targets should be on a new line unless there is
                                   | only one select target. [layout.select_targets]
            All Finished!
            """
        )
        in result.stderr
    )


def test_multiple_targets_fix(multiple_queries: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(multiple_queries) as tmpdir:
        result = run_pants([*args, "fix", f"{tmpdir}/project:"])
        files = collect_files(tmpdir)
    result.assert_success()
    assert "sqlfluff made changes." in result.stderr
    assert files["project/good.sql"] == GOOD_FILE
    assert files["project/bad.sql"] == GOOD_FILE
    assert files["project/unformatted.sql"] == GOOD_FILE


def test_multiple_targets_fmt(multiple_queries: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(multiple_queries) as tmpdir:
        result = run_pants([*args, "fmt", f"{tmpdir}/project:"])
        files = collect_files(tmpdir)
    result.assert_success()
    assert "sqlfluff format made changes." in result.stderr
    assert files["project/good.sql"] == GOOD_FILE
    assert files["project/bad.sql"] == BAD_FILE
    assert files["project/unformatted.sql"] == GOOD_FILE


@pytest.fixture
def skip_queries() -> dict[str, str]:
    return {
        "project/good.sql": GOOD_FILE,
        "project/bad.sql": BAD_FILE,
        "project/unformatted.sql": UNFORMATTED_FILE,
        "project/BUILD": "sql_sources(skip_sqlfluff=True)",
    }


def test_skip_field_lint(skip_queries: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(skip_queries) as tmpdir:
        result = run_pants([*args, "lint", f"{tmpdir}/project:"])
    result.assert_success()


def test_skip_field_fix(skip_queries: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(skip_queries) as tmpdir:
        result = run_pants([*args, "fix", f"{tmpdir}/project:"])
        files = collect_files(tmpdir)
    result.assert_success()
    assert files["project/good.sql"] == GOOD_FILE
    assert files["project/bad.sql"] == BAD_FILE
    assert files["project/unformatted.sql"] == UNFORMATTED_FILE


def test_skip_field_fmt(skip_queries: dict[str, str], args: list[str]) -> None:
    with setup_tmpdir(skip_queries) as tmpdir:
        result = run_pants([*args, "fmt", f"{tmpdir}/project:"])
        files = collect_files(tmpdir)
    result.assert_success()
    assert files["project/good.sql"] == GOOD_FILE
    assert files["project/bad.sql"] == BAD_FILE
    assert files["project/unformatted.sql"] == UNFORMATTED_FILE


@pytest.mark.parametrize(
    "file_path,config_path,extra_args,should_change",
    (
        [Path("query.sql"), Path("pyproject.toml"), [], False],
        [Path("query.sql"), Path(".sqlfluff"), [], False],
        [Path("custom/query.sql"), Path("custom/pyproject.toml"), [], False],
        [Path("custom/query.sql"), Path("custom/.sqlfluff"), [], False],
        [
            Path("query.sql"),
            Path("custom/config.sqlfluff"),
            ["--sqlfluff-config=custom/config.sqlfluff"],
            False,
        ],
        [
            Path("query.sql"),
            Path("custom/.sqlfluff"),
            ['--sqlfluff-args="--dialect=postgres"'],
            True,
        ],
    ),
)
def test_config_file(
    rule_runner: RuleRunner,
    file_path: Path,
    config_path: Path,
    extra_args: list[str],
    should_change: bool,
) -> None:
    if config_path.stem == "pyproject":
        config = dedent(
            """\
            [tool.sqlfluff.core]
            dialect = "postgres"
            exclude_rules = ["RF03"]
            """
        )
    else:
        config = dedent(
            """\
            [sqlfluff]
            dialect = postgres
            exclude_rules = RF03
            """
        )

    rule_runner.write_files(
        {
            file_path: BAD_FILE,
            file_path.parent / "BUILD": "sql_sources()",
            config_path: config,
        }
    )

    spec_path = str(file_path.parent).replace(".", "")
    rel_file_path = file_path.relative_to(*file_path.parts[:1]) if spec_path else file_path
    address = Address(spec_path, relative_file_path=str(rel_file_path))
    fix_result, lint_result, _ = run_sqlfluff(
        rule_runner,
        [address],
        extra_args=extra_args,
    )
    assert lint_result.exit_code == (1 if should_change else 0)
    assert fix_result.did_change is should_change
