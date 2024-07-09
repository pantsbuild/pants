# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Sequence

import pytest

from pants.core.goals.lint import LintResult, Partitions
from pants.core.target_types import FileTarget
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import QueryRule, RuleRunner

from .rules import PartitionMetadata, SemgrepLintRequest
from .rules import rules as semgrep_rules
from .subsystem import SemgrepFieldSet, SemgrepSubsystem
from .subsystem import rules as semgrep_subsystem_rules

DIR = "src"
FILE = "file.txt"

# https://semgrep.dev/docs/cli-reference/#exit-codes
SEMGREP_ERROR_FAILURE_RETURN_CODE = 1

GOOD_FILE = "nothing_bad"
BAD_FILE = "bad_pattern\nalso_bad"
RULES = dedent(
    """\
    rules:
    - id: find-bad-pattern
      patterns:
        - pattern: bad_pattern
      message: >-
        bad pattern found!
      languages: [generic]
      severity: ERROR
      paths:
        # 'generic' means this finds itself
        exclude:
         - '*.yml'
    """
)
RULES2 = dedent(
    """\
    rules:
    - id: find-another-bad-pattern
      patterns:
        - pattern: also_bad
      message: >-
        second bad found!
      languages: [generic]
      severity: ERROR
      paths:
        # 'generic' means this finds itself
        exclude:
         - '*.yml'
    """
)

SINGLE_FILE_BUILD = dedent(
    f"""\
    file(name="f", source="{FILE}")
    """
)

BAD_FILE_LAYOUT = {
    f"{DIR}/{FILE}": BAD_FILE,
    f"{DIR}/.semgrep.yml": RULES,
    f"{DIR}/BUILD": SINGLE_FILE_BUILD,
}
GOOD_FILE_LAYOUT = {
    f"{DIR}/{FILE}": GOOD_FILE,
    f"{DIR}/.semgrep.yml": RULES,
    f"{DIR}/BUILD": SINGLE_FILE_BUILD,
}


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *semgrep_rules(),
            *semgrep_subsystem_rules(),
            *source_files.rules(),
            QueryRule(Partitions, (SemgrepLintRequest.PartitionRequest,)),
            QueryRule(LintResult, (SemgrepLintRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[FileTarget],
    )


def run_semgrep(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: Sequence[str] = (),
    use_default_semgrep_args: bool = False,
) -> tuple[LintResult, ...]:
    if not use_default_semgrep_args:
        # clear out the default --quiet so that we can check the 'Ran ... rules on ... files:
        # ... findings' output
        extra_args = ("--semgrep-args=[]", *extra_args)

    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.tools.semgrep",
            f"--python-interpreter-constraints={SemgrepSubsystem.default_interpreter_constraints!r}",
            *extra_args,
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    partitions = rule_runner.request(
        Partitions[SemgrepFieldSet, PartitionMetadata],
        [
            SemgrepLintRequest.PartitionRequest(
                tuple(SemgrepFieldSet.create(tgt) for tgt in targets)
            )
        ],
    )

    return tuple(
        rule_runner.request(
            LintResult,
            [SemgrepLintRequest.Batch("", partition.elements, partition.metadata)],
        )
        for partition in partitions
    )


def assert_success(
    rule_runner: RuleRunner, target: Target, *, extra_args: Sequence[str] = ()
) -> None:
    results = run_semgrep(rule_runner, [target], extra_args=extra_args)

    assert len(results) == 1
    result = results[0]
    assert result.stdout == ""
    assert "Ran 1 rule on 1 file: 0 findings" in result.stderr
    assert result.exit_code == 0
    assert result.report == EMPTY_DIGEST


@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(SemgrepSubsystem.default_interpreter_constraints),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files(GOOD_FILE_LAYOUT)
    tgt = rule_runner.get_target(Address(DIR, target_name="f"))
    assert_success(
        rule_runner,
        tgt,
        extra_args=[
            f"--python-interpreter-constraints=['=={major_minor_interpreter}.*']"
        ],
    )


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(BAD_FILE_LAYOUT)
    tgt = rule_runner.get_target(Address(DIR, target_name="f"))

    results = run_semgrep(rule_runner, [tgt])
    assert len(results) == 1
    result = results[0]
    assert "find-bad-pattern" in result.stdout
    assert "Ran 1 rule on 1 file: 1 finding" in result.stderr
    assert result.exit_code == SEMGREP_ERROR_FAILURE_RETURN_CODE
    assert result.report == EMPTY_DIGEST


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{DIR}/good.txt": GOOD_FILE,
            f"{DIR}/bad.txt": BAD_FILE,
            f"{DIR}/.semgrep.yml": RULES,
            f"{DIR}/BUILD": dedent(
                """\
                file(name="g", source="good.txt")
                file(name="b", source="bad.txt")
                """
            ),
        }
    )

    tgts = [
        rule_runner.get_target(Address(DIR, target_name=name)) for name in ["g", "b"]
    ]

    results = run_semgrep(
        rule_runner,
        tgts,
    )
    assert len(results) == 1
    result = results[0]
    assert "find-bad-pattern" in result.stdout
    assert "Ran 1 rule on 2 files: 1 finding" in result.stderr
    assert result.exit_code == SEMGREP_ERROR_FAILURE_RETURN_CODE
    assert result.report == EMPTY_DIGEST


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(
            {
                **BAD_FILE_LAYOUT,
                ".semgrep.yml": RULES2,
            },
            id="via nesting",
        ),
        pytest.param(
            {
                f"{DIR}/bad.txt": BAD_FILE,
                f"{DIR}/BUILD": """file(name="f", source="bad.txt")""",
                ".semgrep/one.yml": RULES,
                ".semgrep/vendored/two.yml": RULES2,
            },
            id="via .semgrep directory",
        ),
        pytest.param(
            {
                f"{DIR}/bad.txt": BAD_FILE,
                f"{DIR}/BUILD": """file(name="f", source="bad.txt")""",
                ".semgrep/one.yml": RULES,
                ".semgrep/vendored/two.yml": RULES2,
            },
            id="via recursive .semgrep directory",
        ),
    ],
)
def test_multiple_configs(rule_runner: RuleRunner, files: dict[str, str]) -> None:
    rule_runner.write_files(files)

    tgt = rule_runner.get_target(Address(DIR, target_name="f"))
    results = run_semgrep(rule_runner, [tgt])

    assert len(results) == 1
    result = results[0]
    assert "find-bad-pattern" in result.stdout
    assert "find-another-bad-pattern" in result.stdout
    assert "Ran 2 rules on 1 file: 2 findings" in result.stderr
    assert result.exit_code == SEMGREP_ERROR_FAILURE_RETURN_CODE
    assert result.report == EMPTY_DIGEST


def test_semgrepignore(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({**BAD_FILE_LAYOUT, ".semgrepignore": FILE})

    tgt = rule_runner.get_target(Address(DIR, target_name="f"))
    results = run_semgrep(rule_runner, [tgt])

    assert len(results) == 1
    result = results[0]
    assert result.stdout == ""
    assert "Ran 1 rule on 0 files: 0 findings" in result.stderr
    assert result.exit_code == 0
    assert result.report == EMPTY_DIGEST


def test_partition_by_config(rule_runner: RuleRunner) -> None:
    file_dirs = []

    def file___(dir: str) -> dict[str, str]:
        file_dirs.append(dir)
        return {
            f"{dir}/{FILE}": GOOD_FILE,
            f"{dir}/BUILD": f"""file(name="f", source="{FILE}")""",
        }

    def semgrep(dir: str) -> dict[str, str]:
        return {f"{dir}/.semgrep.yml": RULES}

    rule_runner.write_files(
        {
            # 'y'/'n' indicates whether that level has semgrep config
            **semgrep("y"),
            **file___("y/dir1"),
            **file___("y/dir2"),
            **file___("y/n/dir1"),
            **file___("y/n/dir2"),
            **semgrep("y/y"),
            **file___("y/y/dir1"),
            **file___("y/y/dir2"),
            **file___("n"),
        }
    )

    field_sets = tuple(
        SemgrepFieldSet.create(rule_runner.get_target(Address(dir, target_name="f")))
        for dir in file_dirs
    )

    partitions = rule_runner.request(
        Partitions[SemgrepFieldSet, PartitionMetadata],
        [SemgrepLintRequest.PartitionRequest(field_sets)],
    )

    sorted_partitions = sorted(
        (
            sorted(field_set.address.spec for field_set in partition.elements),
            sorted(str(f) for f in partition.metadata.config_files),
        )
        for partition in partitions
    )

    assert sorted_partitions == [
        (
            ["y/dir1:f", "y/dir2:f", "y/n/dir1:f", "y/n/dir2:f"],
            ["y/.semgrep.yml"],
        ),
        (
            ["y/y/dir1:f", "y/y/dir2:f"],
            ["y/.semgrep.yml", "y/y/.semgrep.yml"],
        ),
        # n: doesn't appear in any partition
    ]


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(BAD_FILE_LAYOUT)
    tgt = rule_runner.get_target(Address(DIR, target_name="f"))

    results = run_semgrep(rule_runner, [tgt], extra_args=["--semgrep-skip"])
    assert not results


@pytest.mark.xfail(
    reason=""" TODO: --semgrep-force does rerun the underlying process, but the LintResult's
    contents are the same (same stdout etc.), these are deduped, and thus we cannot detect the
    rerun""",
    # no point spending time on this
    run=False,
)
def test_force(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(GOOD_FILE_LAYOUT)
    tgt = rule_runner.get_target(Address(DIR, target_name="f"))

    # Should not receive a memoized result if force=True.
    results1 = run_semgrep(rule_runner, [tgt], extra_args=["--semgrep-force"])
    results2 = run_semgrep(rule_runner, [tgt], extra_args=["--semgrep-force"])

    assert len(results1) == len(results2) == 1
    assert results1[0].exit_code == results2[0].exit_code == 0
    assert results1[0] is not results2[0]

    # But should if force=False.
    results1 = run_semgrep(rule_runner, [tgt])
    results2 = run_semgrep(rule_runner, [tgt])
    assert len(results1) == len(results2) == 1
    assert results1[0].exit_code == results2[0].exit_code == 0
    assert results1[0] is results2[0]


def test_default_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(BAD_FILE_LAYOUT)
    tgt = rule_runner.get_target(Address(DIR, target_name="f"))

    results = run_semgrep(rule_runner, [tgt], use_default_semgrep_args=True)
    assert len(results) == 1
    result = results[0]
    assert "find-bad-pattern" in result.stdout
    assert result.stderr == ""
    assert result.exit_code == SEMGREP_ERROR_FAILURE_RETURN_CODE
    assert result.report == EMPTY_DIGEST


def test_extra_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(BAD_FILE_LAYOUT)
    tgt = rule_runner.get_target(Address(DIR, target_name="f"))

    results = run_semgrep(rule_runner, [tgt], extra_args=["--semgrep-args=--quiet"])
    assert len(results) == 1
    result = results[0]
    assert "find-bad-pattern" in result.stdout
    assert result.stderr == ""
    assert result.exit_code == SEMGREP_ERROR_FAILURE_RETURN_CODE
    assert result.report == EMPTY_DIGEST


def test_semgrep_pex_contents_is_ignored(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            # Validate that this doesn't traverse into the PEX created for semgrep itself: a
            # top-level __main__.py will translate into --include=__main__.py (aka **/__main__.py)
            # which will, naively, find the __main__.py in the PEX.
            "__main__.py": "",
            ".semgrep.yml": RULES,
            "BUILD": """file(name="f", source="__main__.py")""",
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="f"))
    results = run_semgrep(rule_runner, [tgt])

    assert len(results) == 1
    result = results[0]
    assert result.stdout == ""
    # Without the --exclude, this would run on 2 files.
    assert "Ran 1 rule on 1 file: 0 findings" in result.stderr
    assert result.exit_code == 0
