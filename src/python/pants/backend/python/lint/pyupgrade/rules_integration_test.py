# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.pyupgrade.rules import PyUpgradeFieldSet, PyUpgradeRequest
from pants.backend.python.lint.pyupgrade.rules import rules as pyupgrade_rules
from pants.backend.python.lint.pyupgrade.subsystem import PyUpgrade
from pants.backend.python.lint.pyupgrade.subsystem import rules as pyupgrade_subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.native_engine import Snapshot
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pyupgrade_rules(),
            *pyupgrade_subsystem_rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(FmtResult, (PyUpgradeRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


# see: https://github.com/asottile/pyupgrade#redundant-open-modes
PY_36_GOOD_FILE = "open('hello.txt')"
PY_36_BAD_FILE = "open('jerry.txt', 'r')"
PY_36_FIXED_BAD_FILE = "open('jerry.txt')"

# see: https://github.com/asottile/pyupgrade#is--is-not-comparison-to-constant-literals
PY_38_BAD_FILE = "x is 920"
PY_38_FIXED_BAD_FILE = "x == 920"


def run_pyupgrade(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
    pyupgrade_arg: str = "--py36-plus",
) -> FmtResult:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python.lint.pyupgrade",
            f'--pyupgrade-args="{pyupgrade_arg}"',
            *(extra_args or ()),
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    field_sets = [PyUpgradeFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.source for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            PyUpgradeRequest(field_sets, snapshot=input_sources.snapshot),
        ],
    )
    return fmt_result


def get_snapshot(rule_runner: RuleRunner, source_files: dict[str, str]) -> Snapshot:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    digest = rule_runner.request(Digest, [CreateDigest(files)])
    return rule_runner.request(Snapshot, [digest])


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(PyUpgrade.default_interpreter_constraints),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"f.py": PY_36_GOOD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_pyupgrade(
        rule_runner,
        [tgt],
        extra_args=[f"--pyupgrade-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )
    assert fmt_result.output == get_snapshot(rule_runner, {"f.py": PY_36_GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": PY_36_BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_pyupgrade(rule_runner, [tgt])
    assert fmt_result.skipped is False
    assert fmt_result.output == get_snapshot(rule_runner, {"f.py": PY_36_FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.py": PY_36_GOOD_FILE, "bad.py": PY_36_BAD_FILE, "BUILD": "python_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.py")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.py")),
    ]
    fmt_result = run_pyupgrade(rule_runner, tgts)
    assert fmt_result.output == get_snapshot(
        rule_runner, {"good.py": PY_36_GOOD_FILE, "bad.py": PY_36_FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"some_file_name.py": PY_38_BAD_FILE, "BUILD": "python_sources(name='t')"}
    )
    tgt = rule_runner.get_target(
        Address("", target_name="t", relative_file_path="some_file_name.py")
    )
    fmt_result = run_pyupgrade(
        rule_runner,
        [tgt],
        pyupgrade_arg="--py38-plus",
    )
    assert fmt_result.output == get_snapshot(
        rule_runner, {"some_file_name.py": PY_38_FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.py": PY_36_BAD_FILE, "BUILD": "python_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.py"))
    fmt_result = run_pyupgrade(rule_runner, [tgt], extra_args=["--pyupgrade-skip"])
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False
