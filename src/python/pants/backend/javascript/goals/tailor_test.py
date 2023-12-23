# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.backend.javascript.goals import tailor
from pants.backend.javascript.goals.tailor import (
    PutativeJSTargetsRequest,
    PutativePackageJsonTargetsRequest,
)
from pants.backend.javascript.package_json import PackageJsonTarget
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSTestsGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.core.util_rules.source_files import ClassifiedSources
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


@pytest.mark.parametrize(
    "files,putative_map",
    [
        pytest.param(
            {
                "src/owned/BUILD": "javascript_sources()\n",
                "src/owned/OwnedFile.js": "",
                "src/unowned/UnownedFile1.js": "",
                "src/unowned/UnownedFile2.mjs": "",
                "src/unowned/UnownedFile3.cjs": "",
            },
            [
                ClassifiedSources(
                    JSSourcesGeneratorTarget,
                    ["UnownedFile1.js", "UnownedFile2.mjs", "UnownedFile3.cjs"],
                )
            ],
            id="only_javascript_sources",
        ),
        pytest.param(
            {
                "src/owned/BUILD": "javascript_sources()\n",
                "src/owned/OwnedFile.js": "",
                "src/unowned/UnownedFile1.test.js": "",
                "src/unowned/UnownedFile2.test.mjs": "",
                "src/unowned/UnownedFile3.test.cjs": "",
            },
            [
                ClassifiedSources(
                    JSTestsGeneratorTarget,
                    ["UnownedFile1.test.js", "UnownedFile2.test.mjs", "UnownedFile3.test.cjs"],
                    "tests",
                )
            ],
            id="only_javascript_tests",
        ),
        pytest.param(
            {
                "src/owned/BUILD": "javascript_sources()\n",
                "src/owned/OwnedFile.js": "",
                "src/unowned/UnownedFile1.js": "",
                "src/unowned/UnownedFile1.test.js": "",
            },
            [
                ClassifiedSources(JSTestsGeneratorTarget, ["UnownedFile1.test.js"], "tests"),
                ClassifiedSources(JSSourcesGeneratorTarget, ["UnownedFile1.js"]),
            ],
            id="both_tests_and_source",
        ),
    ],
)
def test_find_putative_js_targets(
    rule_runner: RuleRunner, files: dict, putative_map: list[ClassifiedSources]
) -> None:
    rule_runner.write_files(files)
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeJSTargetsRequest(("src/owned", "src/unowned")),
            AllOwnedSources(["src/owned/OwnedFile.js"]),
        ],
    )
    expected_targets = PutativeTargets(
        [
            PutativeTarget.for_target_type(
                source_class.target_type, "src/unowned", source_class.name, source_class.files
            )
            for source_class in putative_map
        ]
    )
    assert putative_targets == expected_targets


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
