from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.sql.lint.sqlfluff import rules as sqlfluff_rules
from pants.backend.sql.lint.sqlfluff import skip_field
from pants.backend.sql.lint.sqlfluff import subsystem as sqlfluff_subsystem
from pants.backend.sql.lint.sqlfluff.rules import (
    SqlfluffFieldSet,
    SqlfluffFixRequest,
    SqlfluffFormatRequest,
    SqlfluffLintRequest,
)
from pants.backend.sql.lint.sqlfluff.skip_field import SkipSqlfluffField
from pants.backend.sql.target_types import SqlSourcesGeneratorTarget
from pants.core.goals.fix import FixResult
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult
from pants.core.util_rules import config_files
from pants.core.util_rules.partitions import _EmptyMetadata
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner

GOOD_FILE = "select\n    e.id,\n    e.name\nfrom employees as e\n"
BAD_FILE = "select\n    e.id,\n    name\nfrom employees as e\n"
UNFORMATTED_FILE = "select e.id, e.name\nfrom employees as e\n"


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
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> tuple[FixResult, LintResult, FmtResult]:
    args = ["--backend-packages=pants.backend.sql.lint.sqlfluff", *(extra_args or ())]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})

    field_sets = [
        SqlfluffFieldSet.create(tgt) for tgt in targets if SqlfluffFieldSet.is_applicable(tgt)
    ]
    source_reqs = [SourceFilesRequest(field_set.source for field_set in field_sets)]
    input_sources = rule_runner.request(SourceFiles, source_reqs)

    fix_result = rule_runner.request(
        FixResult,
        [
            SqlfluffFixRequest.Batch(
                "",
                tuple(field_sets),
                partition_metadata=_EmptyMetadata(),
                snapshot=input_sources.snapshot,
            ),
        ],
    )
    lint_result = rule_runner.request(
        LintResult,
        [
            SqlfluffLintRequest.Batch(
                "",
                tuple(field_sets),
                partition_metadata=_EmptyMetadata(),
            ),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            SqlfluffFormatRequest.Batch(
                "",
                tuple(field_sets),
                partition_metadata=_EmptyMetadata(),
                snapshot=input_sources.snapshot,
            )
        ],
    )

    return fix_result, lint_result, fmt_result


@pytest.mark.platform_specific_behavior
def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "query.sql": GOOD_FILE,
            "BUILD": "sql_sources(name='t')",
            ".sqlfluff": dedent(
                """\
                [sqlfluff]
                dialect = postgres
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="query.sql"))
    fix_result, lint_result, fmt_result = run_sqlfluff(rule_runner, [tgt])
    assert fix_result.stdout == dedent(
        """\
        ==== finding fixable violations ====
        ==== no fixable linting violations found ====
        All Finished!
        """
    )
    assert fix_result.stderr == ""
    assert lint_result.exit_code == 0
    assert not fix_result.did_change
    assert fix_result.output == rule_runner.make_snapshot({"query.sql": GOOD_FILE})
    assert not fmt_result.did_change
    assert fmt_result.output == rule_runner.make_snapshot({"query.sql": GOOD_FILE})


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "query.sql": BAD_FILE,
            "BUILD": "sql_sources(name='t')",
            ".sqlfluff": dedent(
                """\
                [sqlfluff]
                dialect = postgres
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="query.sql"))
    fix_result, lint_result, fmt_result = run_sqlfluff(rule_runner, [tgt])
    assert fix_result.stdout == dedent(
        """\
        ==== finding fixable violations ====
        == [query.sql] FAIL
        L:   3 | P:   5 | RF03 | Unqualified reference 'name' found in single table
                               | select. [references.consistent]
        == [query.sql] FIXED
        1 fixable linting violations found
          [1 unfixable linting violations found]
        """
    )
    assert fix_result.stderr == ""
    assert lint_result.exit_code == 1
    assert fix_result.did_change
    assert fix_result.output == rule_runner.make_snapshot({"query.sql": GOOD_FILE})
    assert not fmt_result.did_change
    assert fmt_result.output == rule_runner.make_snapshot({"query.sql": BAD_FILE})


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.py": GOOD_FILE,
            "bad.py": BAD_FILE,
            "unformatted.py": UNFORMATTED_FILE,
            "BUILD": "sql_sources(name='t')",
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="unformatted.py")),
    ]
    fix_result, lint_result, fmt_result = run_sqlfluff(rule_runner, tgts)
    assert lint_result.exit_code == 1
    assert fix_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "bad.py": GOOD_FILE, "unformatted.py": UNFORMATTED_FILE}
    )
    assert fix_result.did_change is True
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "unformatted.py": GOOD_FILE}
    )
    assert fmt_result.did_change is True


def test_skip_field(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.py": GOOD_FILE,
            "bad.py": BAD_FILE,
            "unformatted.py": UNFORMATTED_FILE,
            "BUILD": "sql_sources(name='t', skip_sqlfluff=True)",
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="unformatted.py")),
    ]
    for tgt in tgts:
        assert tgt.get(SkipSqlfluffField).value is True

    fix_result, lint_result, fmt_result = run_sqlfluff(rule_runner, tgts)

    assert lint_result.exit_code == 1
    assert fix_result.output == rule_runner.make_snapshot({})
    assert fix_result.did_change is False
    assert fmt_result.output == rule_runner.make_snapshot({})
    assert fmt_result.did_change is False


def test_skip_check_field(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.py": GOOD_FILE,
            "bad.py": BAD_FILE,
            "unformatted.py": UNFORMATTED_FILE,
            "BUILD": "sql_sources(name='t', skip_sqlfluff=True)",
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="unformatted.py")),
    ]
    for tgt in tgts:
        assert tgt.get(SkipSqlfluffField).value is True

    fix_result, lint_result, fmt_result = run_sqlfluff(rule_runner, tgts)

    assert lint_result.exit_code == 1
    assert fix_result.output == rule_runner.make_snapshot({})
    assert fix_result.did_change is False
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "unformatted.py": GOOD_FILE}
    )
    assert fmt_result.did_change is True


def test_skip_format_field(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.py": GOOD_FILE,
            "bad.py": BAD_FILE,
            "unformatted.py": UNFORMATTED_FILE,
            "BUILD": "sql_sources(name='t', skip_sqlfluff_format=True)",
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="unformatted.py")),
    ]
    for tgt in tgts:
        assert tgt.get(SkipSqlfluffField).value is True

    fix_result, lint_result, fmt_result = run_sqlfluff(rule_runner, tgts)

    assert lint_result.exit_code == 1
    assert fix_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "bad.py": GOOD_FILE, "unformatted.py": UNFORMATTED_FILE}
    )
    assert fix_result.did_change is True
    assert fmt_result.output == rule_runner.make_snapshot({})
    assert fmt_result.did_change is False


@pytest.mark.parametrize(
    "file_path,config_path,extra_args,should_change",
    (
        [Path("query.sql"), Path("pyproject.toml"), [], False],
        [Path("query.sql"), Path("sqlfluff.toml"), [], False],
        [Path("custom/query.sql"), Path("custom/sqlfluff.toml"), [], False],
        [Path("custom/query.sql"), Path("custom/pyproject.toml"), [], False],
        [
            Path("query.sql"),
            Path("custom/sqlfluff.toml"),
            ["--sqlfluff-config=custom/sqlfluff.toml"],
            False,
        ],
        [Path("query.sql"), Path("custom/sqlfluff.toml"), [], True],
    ),
)
def test_config_file(
    rule_runner: RuleRunner,
    file_path: Path,
    config_path: Path,
    extra_args: list[str],
    should_change: bool,
) -> None:
    hierarchy = "[tool.sqlfluff]\n" if config_path.stem == "pyproject" else ""
    rule_runner.write_files(
        {
            file_path: BAD_FILE,
            file_path.parent / "BUILD": "sql_sources()",
            config_path: f'{hierarchy}ignore = ["F541"]',
        }
    )
    spec_path = str(file_path.parent).replace(".", "")
    rel_file_path = file_path.relative_to(*file_path.parts[:1]) if spec_path else file_path
    addr = Address(spec_path, relative_file_path=str(rel_file_path))
    tgt = rule_runner.get_target(addr)
    fix_result, lint_result, _ = run_sqlfluff(rule_runner, [tgt], extra_args=extra_args)
    assert lint_result.exit_code == bool(should_change)
    assert fix_result.did_change is should_change
