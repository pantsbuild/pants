# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re

import pytest

from pants.backend.helm.subsystems import unittest
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.core.util_rules import external_tool
from pants.engine import process
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.process import ProcessResult
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *external_tool.rules(),
            *tool.rules(),
            *process.rules(),
            *unittest.rules(),
            QueryRule(ProcessResult, (HelmProcess,)),
        ]
    )


def test_install_plugin(rule_runner: RuleRunner) -> None:
    plugin_ls_process = HelmProcess(
        argv=["plugin", "ls"],
        input_digest=EMPTY_DIGEST,
        description="Verify installation of Helm plugins",
    )

    process_result = rule_runner.request(ProcessResult, [plugin_ls_process])
    plugin_table = process_result.stdout.decode().splitlines()[1:]
    loaded_plugins = [re.split(r"\t+", line.rstrip())[0] for line in plugin_table]

    assert loaded_plugins == ["unittest"]
