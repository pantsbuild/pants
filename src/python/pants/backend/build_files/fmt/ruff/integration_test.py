# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.build_files.fmt.black.register import BlackRequest
from pants.backend.build_files.fmt.black.register import rules as black_build_rules
from pants.backend.python.lint.black.rules import rules as black_fmt_rules
from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.black.subsystem import rules as black_subsystem_rules
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
            *black_build_rules(),
            *black_fmt_rules(),
            *black_subsystem_rules(),
            *config_files.rules(),
            QueryRule(FmtResult, (BlackRequest.Batch,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )


def run_black(rule_runner: RuleRunner, *, extra_args: list[str] | None = None) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.build_files.fmt.black", *(extra_args or ())],
        # We propagate LANG and LC_ALL to satisfy click, which black depends upon. Without this we
        # see something like the following in CI:
        #
        # RuntimeError: Click will abort further execution because Python was configured to use
        # ASCII as encoding for the environment. Consult
        # https://click.palletsprojects.com/unicode-support/ for mitigation steps.
        #
        # This system supports the C.UTF-8 locale which is recommended. You might be able to
        # resolve your issue by exporting the following environment variables:
        #
        #     export LC_ALL=C.UTF-8
        #     export LANG=C.UTF-8
        #
        env_inherit={"PATH", "PYENV_ROOT", "HOME", "LANG", "LC_ALL"},
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**/BUILD"])])
    fmt_result = rule_runner.request(
        FmtResult,
        [
            BlackRequest.Batch("", snapshot.files, partition_metadata=None, snapshot=snapshot),
        ],
    )
    return fmt_result


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(Black.default_interpreter_constraints),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({"BUILD": 'python_sources(name="t")\n'})
    interpreter_constraint = (
        ">=3.6.2,<3.7" if major_minor_interpreter == "3.6" else f"=={major_minor_interpreter}.*"
    )
    fmt_result = run_black(
        rule_runner,
        extra_args=[f"--black-interpreter-constraints=['{interpreter_constraint}']"],
    )
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": 'python_sources(name="t")\n'})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": "python_sources(name='t')\n"})
    fmt_result = run_black(rule_runner)
    assert "1 file reformatted" in fmt_result.stderr
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": 'python_sources(name="t")\n'})
    assert fmt_result.did_change is True


def test_multiple_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good/BUILD": 'python_sources(name="t")\n',
            "bad/BUILD": "python_sources(name='t')\n",
        }
    )
    fmt_result = run_black(rule_runner)
    assert "1 file reformatted, 1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good/BUILD": 'python_sources(name="t")\n', "bad/BUILD": 'python_sources(name="t")\n'}
    )
    assert fmt_result.did_change is True


@pytest.mark.parametrize(
    "config_path,extra_args",
    (["pyproject.toml", []], ["custom_config.toml", ["--black-config=custom_config.toml"]]),
)
def test_config_file(rule_runner: RuleRunner, config_path: str, extra_args: list[str]) -> None:
    rule_runner.write_files(
        {
            "BUILD": "python_sources(name='t')\n",
            config_path: "[tool.black]\nskip-string-normalization = 'true'\n",
        }
    )
    fmt_result = run_black(rule_runner, extra_args=extra_args)
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": "python_sources(name='t')\n"})
    assert fmt_result.did_change is False


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": "python_sources(name='t')\n"})
    fmt_result = run_black(rule_runner, extra_args=["--black-args='--skip-string-normalization'"])
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.output == rule_runner.make_snapshot({"BUILD": "python_sources(name='t')\n"})
    assert fmt_result.did_change is False
