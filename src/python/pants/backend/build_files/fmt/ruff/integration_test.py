# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.build_files.fmt.ruff.register import RuffRequest
from pants.backend.build_files.fmt.ruff.register import rules as ruff_build_rules
from pants.backend.python.lint.ruff.rules import rules as ruff_fmt_rules
from pants.backend.python.lint.ruff.subsystem import Ruff
from pants.backend.python.lint.ruff.subsystem import rules as ruff_subsystem_rules
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
            *ruff_build_rules(),
            *ruff_fmt_rules(),
            *ruff_subsystem_rules(),
            *config_files.rules(),
            QueryRule(FmtResult, (RuffRequest.Batch,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


def run_ruff(rule_runner: RuleRunner, *, extra_args: list[str] | None = None) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.build_files.fmt.ruff", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**/BUILD"])])
    fmt_result = rule_runner.request(
        FmtResult,
        [
            RuffRequest.Batch("", snapshot.files, partition_metadata=None, snapshot=snapshot),
        ],
    )
    return fmt_result


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(Ruff.default_interpreter_constraints),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"BUILD": 'python_sources(name="t")\n'})
    interpreter_constraint = f"=={major_minor_interpreter}.*"
    fmt_result = run_ruff(
        rule_runner,
        extra_args=[f"--ruff-interpreter-constraints=['{interpreter_constraint}']"],
    )
    assert "1 file left unchanged" in fmt_result.stdout
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": 'python_sources(name="t")\n'})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": "python_sources(name='t')\n"})
    fmt_result = run_ruff(rule_runner)
    assert "1 file reformatted" in fmt_result.stdout
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": 'python_sources(name="t")\n'})
    assert fmt_result.did_change is True


def test_multiple_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good/BUILD": 'python_sources(name="t")\n',
            "bad/BUILD": "python_sources(name='t')\n",
        }
    )
    fmt_result = run_ruff(rule_runner)
    assert "1 file reformatted, 1 file left unchanged" in fmt_result.stdout
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good/BUILD": 'python_sources(name="t")\n', "bad/BUILD": 'python_sources(name="t")\n'}
    )
    assert fmt_result.did_change is True


@pytest.mark.parametrize(
    "config_path,extra_args",
    (["pyproject.toml", []], ["custom_config.toml", ["--ruff-config=custom_config.toml"]]),
)
def test_config_file(rule_runner: RuleRunner, config_path: str, extra_args: list[str]) -> None:
    # Force single-quote formatting to pass config and ensure there are no changes.
    # Use the `tool.ruff` key in pyproject.toml, but don't include in custom config.
    config_content = (
        "[tool.ruff]\n[format]\nquote-style = 'single'\n"
        if config_path == "pyproject.toml"
        else "[format]\nquote-style = 'single'\n"
    )
    rule_runner.write_files(
        {
            "BUILD": "python_sources(name='t')\n",
            config_path: config_content,
        }
    )
    fmt_result = run_ruff(rule_runner, extra_args=extra_args)
    assert "1 file left unchanged" in fmt_result.stdout
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": "python_sources(name='t')\n"})
    assert fmt_result.did_change is False
