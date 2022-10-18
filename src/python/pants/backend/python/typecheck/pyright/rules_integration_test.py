# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.javascript.subsystems.nodejs import rules as nodejs_rules
from pants.backend.python import target_types_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget, PythonSourceTarget
from pants.backend.python.typecheck.pyright.rules import PyrightFieldSet, PyrightRequest
from pants.backend.python.typecheck.pyright.rules import rules as pyright_rules
from pants.core.goals.check import CheckResult, CheckResults
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *nodejs_rules(),
            *pyright_rules(),
            *target_types_rules.rules(),
            QueryRule(CheckResults, (PyrightRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonSourceTarget],
    )


PACKAGE = "src/py/project"
GOOD_FILE = dedent(
    """\
    def add(x: int, y: int) -> int:
        return x + y

    result = add(3, 3)
    """
)
BAD_FILE = dedent(
    """\
    def add(x: int, y: int) -> int:
        return x + y

    result = add(2.0, 3.0)
    """
)


def run_pyright(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[CheckResult, ...]:
    rule_runner.set_options(extra_args or (), env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    result = rule_runner.request(
        CheckResults, [PyrightRequest(PyrightFieldSet.create(tgt) for tgt in targets)]
    )
    return result.results


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": GOOD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pyright(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "0 errors" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pyright(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/f.py:4" in result[0].stdout
    assert "2 errors" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/good.py": GOOD_FILE,
            f"{PACKAGE}/bad.py": BAD_FILE,
            f"{PACKAGE}/BUILD": "python_sources()",
        }
    )
    tgts = [
        rule_runner.get_target(Address(PACKAGE, relative_file_path="good.py")),
        rule_runner.get_target(Address(PACKAGE, relative_file_path="bad.py")),
    ]
    result = run_pyright(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/good.py" not in result[0].stdout
    assert f"{PACKAGE}/bad.py:4" in result[0].stdout
    assert "Found 2 source files" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST
