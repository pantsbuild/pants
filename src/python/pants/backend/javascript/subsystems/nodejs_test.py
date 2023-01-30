# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget
from pants.backend.python import target_types_rules
from pants.core.util_rules import config_files, source_files
from pants.engine.process import ProcessResult
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *nodejs.rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(ProcessResult, [nodejs.NodeJSToolProcess]),
        ],
        target_types=[JSSourcesGeneratorTarget],
    )


def test_npx_process(rule_runner: RuleRunner):
    result = rule_runner.request(
        ProcessResult,
        [
            nodejs.NodeJSToolProcess.npx(
                npm_package="",
                args=("--version",),
                description="Testing NpxProcess",
            )
        ],
    )

    assert result.stdout.strip() == b"8.5.5"


def test_npm_process(rule_runner: RuleRunner):
    result = rule_runner.request(
        ProcessResult,
        [
            nodejs.NodeJSToolProcess.npm(
                args=("--version",),
                description="Testing NpmProcess",
            )
        ],
    )

    assert result.stdout.strip() == b"8.5.5"
