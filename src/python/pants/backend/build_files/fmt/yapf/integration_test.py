# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.build_files.fmt.yapf.register import YapfRequest
from pants.backend.build_files.fmt.yapf.register import rules as yapf_build_rules
from pants.backend.python.lint.yapf.rules import rules as yapf_fmt_rules
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.lint.yapf.subsystem import rules as yapf_subsystem_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import config_files
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Snapshot
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *yapf_build_rules(),
            *yapf_fmt_rules(),
            *yapf_subsystem_rules(),
            *config_files.rules(),
            QueryRule(FmtResult, (YapfRequest.Batch,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


def run_yapf(rule_runner: RuleRunner, *, extra_args: list[str] | None = None) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.build_files.fmt.yapf", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**/BUILD"])])
    fmt_result = rule_runner.request(
        FmtResult,
        [
            YapfRequest.Batch("", snapshot.files, partition_metadata=None, snapshot=snapshot),
        ],
    )
    return fmt_result


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(Yapf.default_interpreter_constraints),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"BUILD": 'python_sources(name="t")\n'})
    interpreter_constraint = (
        ">=3.6.2,<3.7" if major_minor_interpreter == "3.6" else f"=={major_minor_interpreter}.*"
    )
    fmt_result = run_yapf(
        rule_runner,
        extra_args=[f"--yapf-interpreter-constraints=['{interpreter_constraint}']"],
    )
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": 'python_sources(name="t")\n'})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": 'python_sources(name = "t")\n'})
    fmt_result = run_yapf(rule_runner)
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": 'python_sources(name="t")\n'})
    assert fmt_result.did_change is True


def test_multiple_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good/BUILD": 'python_sources(name="t")\n',
            "bad/BUILD": 'python_sources(name = "t")\n',
        }
    )
    fmt_result = run_yapf(rule_runner)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good/BUILD": 'python_sources(name="t")\n', "bad/BUILD": 'python_sources(name="t")\n'},
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
            "BUILD": 'python_sources(name = "t")\n',
            path: f"[{section}]\nspaces_around_default_or_named_assign = True\n",
        }
    )
    fmt_result = run_yapf(rule_runner, extra_args=extra_args)
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": 'python_sources(name = "t")\n'})
    assert fmt_result.did_change is False


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": 'python_sources(name = "t")\n'})
    fmt_result = run_yapf(
        rule_runner,
        extra_args=["--yapf-args=--style='{spaces_around_default_or_named_assign: True}'"],
    )
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": 'python_sources(name = "t")\n'})
    assert fmt_result.did_change is False
