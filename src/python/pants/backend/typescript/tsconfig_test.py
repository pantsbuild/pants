# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json

import pytest

from pants.backend.typescript import tsconfig
from pants.backend.typescript.target_types import TypeScriptSourceTarget
from pants.backend.typescript.tsconfig import AllTSConfigs, TSConfig
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*tsconfig.rules(), QueryRule(AllTSConfigs, ())],
        target_types=[TypeScriptSourceTarget, TargetGeneratorSourcesHelperTarget],
    )


def test_parses_tsconfig(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "project/BUILD": "typescript_source()",
            "project/index.ts": "",
            "project/tsconfig.json": "{}",
        }
    )
    [ts_config] = rule_runner.request(AllTSConfigs, [])
    assert ts_config == TSConfig("project/tsconfig.json")


def test_parses_extended_tsconfig(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "project/BUILD": "typescript_source()",
            "project/index.ts": "",
            "project/tsconfig.json": json.dumps({"compilerOptions": {"baseUrl": "./"}}),
            "project/lib/tsconfig.json": json.dumps({"compilerOptions": {"extends": ".."}}),
        }
    )
    configs = rule_runner.request(AllTSConfigs, [])
    assert set(configs) == {
        TSConfig("project/tsconfig.json", base_url="./"),
        TSConfig("project/lib/tsconfig.json", base_url="./", extends=".."),
    }


def test_parses_extended_tsconfig_with_overrides(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "project/BUILD": "typescript_source()",
            "project/index.ts": "",
            "project/tsconfig.json": json.dumps({"compilerOptions": {"baseUrl": "./"}}),
            "project/lib/tsconfig.json": json.dumps({"compilerOptions": {"baseUrl": "./src", "extends": ".."}}),
        }
    )
    configs = rule_runner.request(AllTSConfigs, [])
    assert set(configs) == {
        TSConfig("project/tsconfig.json", base_url="./"),
        TSConfig("project/lib/tsconfig.json", base_url="./src", extends=".."),
    }
