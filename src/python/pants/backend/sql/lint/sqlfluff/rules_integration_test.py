# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

import os
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
from pants.testutil.rule_runner import QueryRule, RuleRunner

from pants.testutil.pants_integration_test import PantsResult, run_pants

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
    addresses: list[Address],
    *,
    extra_args: list[str] | None = None,
) -> tuple[PantsResult, PantsResult, PantsResult]:
    args = [
        "--backend-packages=pants.backend.experimental.sql.lint.sqlfluff",
        '--sqlfluff-fix-args="--force"',
        *(extra_args or ()),
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})

    addresses_args = [a.spec for a in addresses]

    fix_result = run_pants(command=[*args, "fix", *addresses_args])
    lint_result = run_pants(command=[*args, "lint", *addresses_args])
    fmt_result = run_pants(command=[*args, "fmt", *addresses_args])
    return fix_result, lint_result, fmt_result


def collect_files(rootdir: str) -> dict:
    result = {}
    for root, _, files in os.walk(rootdir):
        for file in files:
            path = f"{root}/{file}"
            result[path] = Path(path).read_text()
    return result


@pytest.mark.platform_specific_behavior
def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "query.sql": GOOD_FILE,
            "BUILD": "sql_sources(name='t')",
            ".sqlfluff": CONFIG_POSTGRES,
        }
    )
    address = Address("", target_name="t", relative_file_path="query.sql")
    fix_result, lint_result, fmt_result = run_sqlfluff(rule_runner, [address])
    assert fix_result.stderr == ""
    assert fix_result.stdout == dedent(
        """\
        ==== finding fixable violations ====
        FORCE MODE: Attempting fixes...
        ==== no fixable linting violations found ====
        All Finished!
        """
    )
    assert fix_result.stderr == ""
    assert lint_result.exit_code == 0
    assert collect_files(fix_result.workdir) == {"query.sql": GOOD_FILE}
    assert collect_files(fmt_result.workdir) == {"query.sql": GOOD_FILE}


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "query.sql": BAD_FILE,
            "BUILD": "sql_sources(name='t')",
            ".sqlfluff": CONFIG_POSTGRES,
        }
    )
    address = Address("", target_name="t", relative_file_path="query.sql")
    fix_result, lint_result, fmt_result = run_sqlfluff(rule_runner, [address])
    assert fix_result.stdout == dedent(
        """\
        ==== finding fixable violations ====
        FORCE MODE: Attempting fixes...
        == [query.sql] FAIL
        L:   3 | P:   5 | RF03 | Unqualified reference 'name' found in single table
                               | select. [references.consistent]
        == [query.sql] FIXED
        1 fixable linting violations found
          [1 unfixable linting violations found]
        """
    )
    assert fix_result.stderr == ""
    assert lint_result.stdout == dedent(
        """\
         == [query.sql] FAIL
         L:   3 | P:   5 | RF03 | Unqualified reference 'name' found in single table
                                | select. [references.consistent]
         L:   3 | P:   5 | RF03 | Unqualified reference 'name' found in single table
                                | select which is inconsistent with previous references.
                                | [references.consistent]
         All Finished!
         """
    )
    assert lint_result.stderr == ""
    assert lint_result.exit_code == 1
    assert fix_result.did_change
    assert fix_result.output == rule_runner.make_snapshot({"query.sql": GOOD_FILE})
    assert not fmt_result.did_change
    assert fmt_result.output == rule_runner.make_snapshot({"query.sql": BAD_FILE})


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.sql": GOOD_FILE,
            "bad.sql": BAD_FILE,
            "unformatted.sql": UNFORMATTED_FILE,
            "BUILD": "sql_sources(name='t')",
            ".sqlfluff": CONFIG_POSTGRES,
        }
    )
    addresses = [
        Address("", target_name="t", relative_file_path="good.sql"),
        Address("", target_name="t", relative_file_path="bad.sql"),
        Address("", target_name="t", relative_file_path="unformatted.sql"),
    ]
    fix_result, lint_result, fmt_result = run_sqlfluff(rule_runner, addresses)
    assert lint_result.exit_code == 1
    assert fix_result.output == rule_runner.make_snapshot(
        {"good.sql": GOOD_FILE, "bad.sql": GOOD_FILE, "unformatted.sql": GOOD_FILE}
    )
    assert fix_result.did_change is True
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.sql": GOOD_FILE, "bad.sql": BAD_FILE, "unformatted.sql": GOOD_FILE}
    )
    assert fmt_result.did_change is True


def test_skip_field(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.sql": GOOD_FILE,
            "bad.sql": BAD_FILE,
            "unformatted.sql": UNFORMATTED_FILE,
            "BUILD": "sql_sources(name='t', skip_sqlfluff=True)",
        }
    )
    addresses = [
        Address("", target_name="t", relative_file_path="good.sql"),
        Address("", target_name="t", relative_file_path="bad.sql"),
        Address("", target_name="t", relative_file_path="unformatted.sql"),
    ]

    fix_result, lint_result, fmt_result = run_sqlfluff(rule_runner, addresses)

    assert lint_result.exit_code == 0
    assert fix_result.output == rule_runner.make_snapshot({})
    assert fix_result.did_change is False
    assert fmt_result.output == rule_runner.make_snapshot({})
    assert fmt_result.did_change is False


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
    rel_file_path = (
        file_path.relative_to(*file_path.parts[:1]) if spec_path else file_path
    )
    address = Address(spec_path, relative_file_path=str(rel_file_path))
    fix_result, lint_result, _ = run_sqlfluff(
        rule_runner,
        [address],
        extra_args=extra_args,
    )
    assert lint_result.exit_code == (1 if should_change else 0)
    assert fix_result.did_change is should_change
