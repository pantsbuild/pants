# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.add_trailing_comma.rules import (
    AddTrailingCommaFieldSet,
    AddTrailingCommaRequest,
)
from pants.backend.python.lint.add_trailing_comma.rules import rules as add_trailing_comma_rules
from pants.backend.python.lint.add_trailing_comma.subsystem import AddTrailingComma
from pants.backend.python.lint.add_trailing_comma.subsystem import (
    rules as add_trailing_comma_subsystem_rules,
)
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *add_trailing_comma_rules(),
            *add_trailing_comma_subsystem_rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(FmtResult, (AddTrailingCommaRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


GOOD_FILE = "foobar = [1, 2]\nbazqux = [\n  1,\n  2,\n]\n"
BAD_FILE = "foobar = [1, 2,]\nbazqux = [\n  1,\n  2\n]\n"


def run_add_trailing_comma(
    rule_runner: PythonRuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python.lint.add_trailing_comma", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [AddTrailingCommaFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.source for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            AddTrailingCommaRequest.Batch(
                "",
                input_sources.snapshot.files,
                partition_metadata=None,
                snapshot=input_sources.snapshot,
            ),
        ],
    )
    return fmt_result


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(AddTrailingComma.default_interpreter_constraints),
)
def test_passing_source(rule_runner: PythonRuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_add_trailing_comma(
        rule_runner,
        [tgt],
        extra_args=[
            f"--add-trailing-comma-interpreter-constraints=['=={major_minor_interpreter}.*']"
        ],
    )
    assert fmt_result.stdout == ""
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing_source(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_add_trailing_comma(rule_runner, [tgt])
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": GOOD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "BUILD": "python_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    fmt_result = run_add_trailing_comma(rule_runner, tgts)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "bad.py": GOOD_FILE}
    )
    assert fmt_result.did_change is True


def test_stub_files(rule_runner: PythonRuleRunner) -> None:
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
    fmt_result = run_add_trailing_comma(rule_runner, good_tgts)
    assert fmt_result.stdout == ""
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "good.pyi": GOOD_FILE}
    )
    assert not fmt_result.did_change

    bad_tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.pyi")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    fmt_result = run_add_trailing_comma(rule_runner, bad_tgts)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"bad.py": GOOD_FILE, "bad.pyi": GOOD_FILE}
    )
    assert fmt_result.did_change
