# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re

import pytest

from pants.backend.helm.subsystems import unittest as unittest_subsystem
from pants.backend.helm.subsystems.unittest import HelmUnitTestSubsystem
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.process import ProcessResult
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tool.rules(),
            *unittest_subsystem.rules(),
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

    # The result of the `helm plugin ls` command is a table with a header like
    #    NAME           VERSION DESCRIPTION
    #    plugin_name    0.1.0   Some plugin description
    #
    # So to build the test expectation we parse that output keeping
    # the plugin's name and version to be used in the comparison
    plugin_table_rows = process_result.stdout.decode().splitlines()[1:]
    loaded_plugins = [
        (columns[0].strip(), columns[1].strip())
        for columns in (re.split(r"\t+", line.rstrip()) for line in plugin_table_rows)
    ]

    assert loaded_plugins == [
        (HelmUnitTestSubsystem.plugin_name, HelmUnitTestSubsystem.default_version)
    ]
