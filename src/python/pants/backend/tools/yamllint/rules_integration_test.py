# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from typing import Any

import pytest

from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.tools.yamllint.rules import YamllintFieldSet, YamllintRequest
from pants.backend.tools.yamllint.rules import rules as yamllint_rules
from pants.backend.tools.yamllint.target_types import YamlSourcesGeneratorTarget, YamlSourceTarget
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, external_tool, source_files
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *yamllint_rules(),
            *config_files.rules(),
            *source_files.rules(),
            *external_tool.rules(),
            *pex_rules(),
            QueryRule(Partitions, [YamllintRequest.PartitionRequest]),
            QueryRule(LintResult, [YamllintRequest.Batch]),
        ],
        target_types=[
            YamlSourceTarget,
            YamlSourcesGeneratorTarget,
        ],
    )


GOOD_FILE = """
this: is
valid: YAML
"""


def run_yamllint(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[LintResult, ...]:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.tools.yamllint", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT"},
    )
    partitions = rule_runner.request(
        Partitions[YamllintFieldSet, Any],
        [YamllintRequest.PartitionRequest(tuple(YamllintFieldSet.create(tgt) for tgt in targets))],
    )
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [YamllintRequest.Batch("", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"test.yaml": GOOD_FILE, "BUILD": "yaml_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="test.yaml"))
    result = run_yamllint(rule_runner, [tgt])
    print(f"run_yamllint result: {result}", file=sys.stderr)
    assert False
