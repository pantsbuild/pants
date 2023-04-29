# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.docformatter.rules import DocformatterFieldSet, DocformatterRequest
from pants.backend.python.lint.docformatter.rules import rules as docformatter_rules
from pants.backend.python.lint.docformatter.subsystem import Docformatter
from pants.backend.python.lint.docformatter.subsystem import rules as docformatter_subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *docformatter_rules(),
            *docformatter_subsystem_rules(),
            *source_files.rules(),
            *target_types_rules.rules(),
            QueryRule(FmtResult, (DocformatterRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


GOOD_FILE = '"""Good docstring."""\n'
BAD_FILE = '"""Oops, missing a period"""\n'
FIXED_BAD_FILE = '"""Oops, missing a period."""\n'


def run_docformatter(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python.lint.docformatter", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [DocformatterFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.source for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            DocformatterRequest.Batch(
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
    all_major_minor_python_versions(Docformatter.default_interpreter_constraints),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_docformatter(
        rule_runner,
        [tgt],
        extra_args=[f"--docformatter-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_docformatter(rule_runner, [tgt])
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.py": GOOD_FILE, "bad.py": BAD_FILE, "BUILD": "python_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    fmt_result = run_docformatter(rule_runner, tgts)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "bad.py": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    content = '"""\nOne line docstring acting like it\'s multiline.\n"""\n'
    rule_runner.write_files({"f.py": content, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_docformatter(
        rule_runner,
        [tgt],
        extra_args=["--docformatter-args='--make-summary-multi-line'"],
    )
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": content})
    assert fmt_result.did_change is False


def test_stub_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.pyi": GOOD_FILE, "bad.pyi": BAD_FILE, "BUILD": "python_sources(name='t')"}
    )

    good_tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="good.pyi"))
    fmt_result = run_docformatter(rule_runner, [good_tgt])
    assert fmt_result.output == rule_runner.make_snapshot({"good.pyi": GOOD_FILE})
    assert not fmt_result.did_change

    bad_tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.pyi"))
    fmt_result = run_docformatter(rule_runner, [bad_tgt])
    assert fmt_result.output == rule_runner.make_snapshot({"bad.pyi": FIXED_BAD_FILE})
    assert fmt_result.did_change
