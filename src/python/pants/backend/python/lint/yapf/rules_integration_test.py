# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.yapf.rules import YapfFieldSet, YapfRequest
from pants.backend.python.lint.yapf.rules import rules as yapf_rules
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.lint.yapf.subsystem import rules as yapf_subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.core.goals.fmt import FmtResult
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
            *yapf_rules(),
            *yapf_subsystem_rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(FmtResult, (YapfRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


GOOD_FILE = "data = []\n"
BAD_FILE = "data = {  'a':11,'b':22    }\n"
FIXED_BAD_FILE = "data = {'a': 11, 'b': 22}\n"

# Note the indentation is 6 spaces; after formatting it should
# become 2 or 4 spaces depending on the configuration
NEEDS_CONFIG_FILE = "def func():\n      return 42\n"
FIXED_NEEDS_CONFIG_FILE_INDENT2 = "def func():\n  return 42\n"
FIXED_NEEDS_CONFIG_FILE_INDENT4 = "def func():\n    return 42\n"


def run_yapf(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python.lint.yapf", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [YapfFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.source for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            YapfRequest.Batch(
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
    all_major_minor_python_versions(Yapf.default_interpreter_constraints),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"f.py": GOOD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_yapf(
        rule_runner,
        [tgt],
        extra_args=[f"--yapf-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_yapf(rule_runner, [tgt])
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
    fmt_result = run_yapf(rule_runner, tgts)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.py": GOOD_FILE, "bad.py": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


@pytest.mark.parametrize(
    "path,section,extra_args",
    (
        (".style.yapf", "style", []),
        ("custom.style", "style", ["--yapf-config=custom.style"]),
    ),
)
def test_config_file(
    rule_runner: RuleRunner, path: str, section: str, extra_args: list[str]
) -> None:
    rule_runner.write_files(
        {
            "f.py": NEEDS_CONFIG_FILE,
            "BUILD": "python_sources(name='t', interpreter_constraints=['==3.9.*'])",
            path: f"[{section}]\nindent_width = 2\n",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_yapf(rule_runner, [tgt], extra_args=extra_args)
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": FIXED_NEEDS_CONFIG_FILE_INDENT2})
    assert fmt_result.did_change is True


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": NEEDS_CONFIG_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_yapf(
        rule_runner, [tgt], extra_args=["--yapf-args=--style='{indent_width: 4}'"]
    )
    assert fmt_result.output == rule_runner.make_snapshot({"f.py": FIXED_NEEDS_CONFIG_FILE_INDENT4})
    assert fmt_result.did_change is True
