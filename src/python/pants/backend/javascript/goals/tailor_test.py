# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.javascript.goals import tailor
from pants.backend.javascript.goals.tailor import (
    PutativeJSTargetsRequest,
    PutativePackageJsonTargetsRequest,
)
from pants.backend.javascript.package_json import PackageJsonTarget
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeJSTargetsRequest, AllOwnedSources)),
            QueryRule(PutativeTargets, (PutativePackageJsonTargetsRequest, AllOwnedSources)),
        ],
        target_types=[JSSourcesGeneratorTarget, PackageJsonTarget],
    )


def test_find_putative_js_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/owned/BUILD": "javascript_sources()\n",
            "src/owned/OwnedFile.js": "",
            "src/unowned/UnownedFile1.js": "",
            "src/unowned/UnownedFile2.mjs": "",
            "src/unowned/UnownedFile3.cjs": "",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeJSTargetsRequest(("src/owned", "src/unowned")),
            AllOwnedSources(["src/owned/OwnedFile.js"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    JSSourcesGeneratorTarget,
                    "src/unowned",
                    "unowned",
                    ["UnownedFile1.js", "UnownedFile2.mjs", "UnownedFile3.cjs"],
                ),
            ]
        )
        == putative_targets
    )


def test_find_putative_package_json_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/owned/BUILD": "package_json()\n",
            "src/owned/package.json": "",
            "src/unowned/package.json": "",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativePackageJsonTargetsRequest(("src/owned", "src/unowned")),
            AllOwnedSources(["src/owned/package.json"]),
        ],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                PackageJsonTarget,
                "src/unowned",
                "unowned",
                ["package.json"],
            ),
        ]
    )
