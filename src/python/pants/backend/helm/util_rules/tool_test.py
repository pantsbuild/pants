# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.util_rules import config_files, external_tool
from pants.engine import process
from pants.engine.platform import Platform
from pants.engine.rules import QueryRule, SubsystemRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[],
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *tool.rules(),
            *process.rules(),
            SubsystemRule(HelmSubsystem),
            QueryRule(HelmBinary, ()),
            QueryRule(HelmSubsystem, ()),
        ],
    )


def test_initialises_basic_helm_binary(rule_runner: RuleRunner) -> None:
    helm_subsystem = rule_runner.request(HelmSubsystem, [])
    helm_binary = rule_runner.request(HelmBinary, [])
    assert helm_binary
    assert helm_binary.path == f"__helm/{helm_subsystem.generate_exe(Platform.current)}"
