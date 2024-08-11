# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.openapi.util_rules import generator_process
from pants.backend.openapi.util_rules.generator_process import (
    OpenAPIGeneratorProcess,
)
from pants.core.util_rules import config_files, external_tool, source_files, system_binaries
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.process import Process
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[],
        rules=[
            *generator_process.rules(),
            *config_files.rules(),
            *source_files.rules(),
            *external_tool.rules(),
            *system_binaries.rules(),
            QueryRule(Process, (OpenAPIGeneratorProcess,)),
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_generator_process(rule_runner: RuleRunner) -> None:
    generator_process = OpenAPIGeneratorProcess(
        generator_name='java',
        argv=["foo"],
        description="Test generator process",
        input_digest=EMPTY_DIGEST,
    )

    process = rule_runner.request(Process, [generator_process])
    assert 'java' in process.argv
    assert "org.openapitools.codegen.OpenAPIGenerator" in process.argv
