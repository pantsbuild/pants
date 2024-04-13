# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.autoflake.rules import AutoflakeFieldSet, AutoflakeRequest
from pants.backend.python.lint.autoflake.rules import rules as autoflake_rules
from pants.backend.python.lint.autoflake.subsystem import Autoflake
from pants.backend.python.lint.autoflake.subsystem import rules as autoflake_subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.core.goals.fix import FixResult
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *autoflake_rules(),
            *autoflake_subsystem_rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(FixResult, (AutoflakeRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


GOOD_FILE = "from foo import Foo\nprint(Foo())\n"
BAD_FILE = "from foo import Foo\nprint(Bar())\n"
FIXED_BAD_FILE = "print(Bar())\n"


def run_autoflake(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> FixResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python.lint.autoflake", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [AutoflakeFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.source for field_set in field_sets),
        ],
    )
    fix_result = rule_runner.request(
        FixResult,
        [
            AutoflakeRequest.Batch(
                "",
                input_sources.snapshot.files,
                partition_metadata=None,
                snapshot=input_sources.snapshot,
            ),
        ],
    )
    return fix_result


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(Autoflake.default_interpreter_constraints),
)
def test_passing_source(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fix_result = run_autoflake(
        rule_runner,
        [tgt],
        extra_args=[f"--autoflake-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )
    assert fix_result.stdout == ""
    assert fix_result.output == rule_runner.make_snapshot({"f.py": GOOD_FILE})
    assert fix_result.did_change is False


def test_failing_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fix_result = run_autoflake(rule_runner, [tgt])
    assert fix_result.output == rule_runner.make_snapshot({"f.py": FIXED_BAD_FILE})
    assert fix_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "BUILD": "python_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    fix_result = run_autoflake(rule_runner, tgts)
    assert fix_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "bad.py": FIXED_BAD_FILE}
    )
    assert fix_result.did_change is True


def test_stub_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.pyi": GOOD_FILE,
            "good.py": GOOD_FILE,
            "bad.pyi": BAD_FILE,
            "bad.py": BAD_FILE,
            "BUILD": "python_sources(name='t')",
        }
    )

    good_tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.pyi")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
    ]
    fix_result = run_autoflake(rule_runner, good_tgts)
    assert fix_result.stdout == ""
    assert fix_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "good.pyi": GOOD_FILE}
    )
    assert not fix_result.did_change

    bad_tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.pyi")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    fix_result = run_autoflake(rule_runner, bad_tgts)
    assert fix_result.output == rule_runner.make_snapshot(
        {"bad.py": FIXED_BAD_FILE, "bad.pyi": FIXED_BAD_FILE}
    )
    assert fix_result.did_change
