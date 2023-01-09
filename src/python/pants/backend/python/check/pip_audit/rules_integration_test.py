# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.check.pip_audit.rules import (
    PipAuditFieldSet,
    PipAuditPartitions,
    PipAuditRequest,
)
from pants.backend.python.check.pip_audit.rules import rules as pip_audit_rules
from pants.backend.python.check.pip_audit.subsystem import rules as pip_audit_subsystem_rules
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
)
from pants.core.goals.check import CheckResult, CheckResults
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner

PASSING_REQ = 'python_requirement(name="freezegun", requirements=["freezegun==1.2.1"])'
FAILING_REQ = 'python_requirement(name="flask", requirements=["Flask==0.5"])'


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pip_audit_rules(),
            *pip_audit_subsystem_rules(),
            *target_types_rules.rules(),
            QueryRule(CheckResults, (PipAuditRequest,)),
            QueryRule(PipAuditPartitions, (PipAuditRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonRequirementTarget, PythonSourceTarget],
    )


def run_pip_audit(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[CheckResult, ...]:
    rule_runner.set_options(extra_args or (), env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    result = rule_runner.request(
        CheckResults, [PipAuditRequest(PipAuditFieldSet.create(tgt) for tgt in targets)]
    )
    return result.results


def assert_success(
    rule_runner: RuleRunner, target: Target, *, extra_args: list[str] | None = None
) -> None:
    result = run_pip_audit(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "No known vulnerabilities found" in result[0].stderr.strip()


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"foobar/BUILD": PASSING_REQ})
    tgt = rule_runner.get_target(Address("foobar", target_name="freezegun"))
    assert_success(
        rule_runner,
        tgt,
    )


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"foobar/BUILD": FAILING_REQ})
    tgt = rule_runner.get_target(Address("foobar", target_name="flask"))
    result = run_pip_audit(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "flask" in result[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"foobar/BUILD": "\n".join((PASSING_REQ, FAILING_REQ))})
    tgts = [
        rule_runner.get_target(Address("foobar", target_name="freezegun")),
        rule_runner.get_target(Address("foobar", target_name="flask")),
    ]
    result = run_pip_audit(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "freezegun" not in result[0].stdout
    assert "flask" in result[0].stdout
    assert "in 1 package" in result[0].stderr


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"foobar/BUILD": FAILING_REQ})
    tgt = rule_runner.get_target(Address("foobar", target_name="flask"))
    result = run_pip_audit(
        rule_runner, [tgt], extra_args=["--pip-audit-args='--ignore-vuln=PYSEC-2019-179'"]
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "PYSEC-2019-179" not in result[0].stdout
    assert "PYSEC-2018-66" in result[0].stdout


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"foobar/BUILD": FAILING_REQ})
    tgt = rule_runner.get_target(Address("foobar", target_name="flask"))
    result = run_pip_audit(rule_runner, [tgt], extra_args=["--pip-audit-skip"])
    assert not result
