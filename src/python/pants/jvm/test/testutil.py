# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from typing import Iterable, Mapping

from pants.core.goals.test import TestResult
from pants.engine.internals.native_engine import Address
from pants.jvm.test.junit import JunitTestFieldSet, JunitTestRequest
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner

ATTEMPTS_DEFAULT_OPTION = 2


def run_junit_test(
    rule_runner: RuleRunner,
    target_name: str,
    relative_file_path: str,
    *,
    extra_args: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> TestResult:
    args = [
        "--junit-args=['--disable-ansi-colors','--details=flat','--details-theme=ascii']",
        f"--test-attempts-default={ATTEMPTS_DEFAULT_OPTION}",
        *(extra_args or ()),
    ]
    rule_runner.set_options(args, env=env, env_inherit=PYTHON_BOOTSTRAP_ENV)
    tgt = rule_runner.get_target(
        Address(spec_path="", target_name=target_name, relative_file_path=relative_file_path)
    )
    return rule_runner.request(
        TestResult, [JunitTestRequest.Batch("", (JunitTestFieldSet.create(tgt),), None)]
    )
