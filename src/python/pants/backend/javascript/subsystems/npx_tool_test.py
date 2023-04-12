# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.subsystems.npx_tool import NpxToolBase
from pants.testutil.rule_runner import QueryRule, RuleRunner


class CowsayTool(NpxToolBase):
    options_scope = "cowsay"
    name = "Cowsay"
    # Intentionally older version.
    default_version = "cowsay@1.4.0"
    help = "The Cowsay utility for printing cowsay messages"


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *nodejs.rules(),
            *CowsayTool.rules(),
            QueryRule(CowsayTool, []),
        ],
    )


def test_version_option_overrides_default(rule_runner: RuleRunner):
    rule_runner.set_options(["--cowsay-version=cowsay@1.5.0"], env_inherit={"PATH"})
    tool = rule_runner.request(CowsayTool, [])
    assert tool.default_version == "cowsay@1.4.0"
    assert tool.version == "cowsay@1.5.0"
