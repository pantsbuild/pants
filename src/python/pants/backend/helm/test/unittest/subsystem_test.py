# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.helm.test.unittest.subsystem import HelmUnitTestPlugin
from pants.backend.helm.test.unittest.subsystem import rules as unittest_rules
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.util_rules import config_files, external_tool
from pants.engine import process
from pants.engine.rules import QueryRule, SubsystemRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *tool.rules(),
            *process.rules(),
            *unittest_rules(),
            SubsystemRule(HelmUnitTestPlugin),
            QueryRule(HelmBinary, ()),
        ]
    )


def test_install_plugin(rule_runner: RuleRunner) -> None:
    helm_setup = rule_runner.request(HelmBinary, [])
    assert helm_setup.loaded_plugins == ("unittest",)
