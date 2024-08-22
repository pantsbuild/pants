# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.backend.jsx.goals import tailor
from pants.backend.jsx.goals.tailor import PutativeJSXTargetsRequest
from pants.backend.jsx.target_types import JSXSourcesGeneratorTarget, JSXTestsGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.core.util_rules.source_files import ClassifiedSources
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeJSXTargetsRequest, AllOwnedSources)),
        ],
        target_types=[JSXTestsGeneratorTarget, JSXSourcesGeneratorTarget],
    )


@pytest.mark.parametrize(
    "files,putative_map",
    [
        pytest.param(
            {
                "src/owned/BUILD": "javascript_sources()\n",
                "src/owned/OwnedFile.jsx": "",
                "src/unowned/UnownedFile1.jsx": "",
                "src/unowned/UnownedFile2.mjsx": "",
                "src/unowned/UnownedFile3.cjsx": "",
            },
            [
                ClassifiedSources(
                    JSXSourcesGeneratorTarget,
                    ["UnownedFile1.jsx", "UnownedFile2.mjsx", "UnownedFile3.cjsx"],
                )
            ],
            id="only_jsx_sources",
        ),
        pytest.param(
            {
                "src/owned/BUILD": "jsx_sources()\n",
                "src/owned/OwnedFile.jsx": "",
                "src/unowned/UnownedFile1.test.jsx": "",
                "src/unowned/UnownedFile2.test.mjsx": "",
                "src/unowned/UnownedFile3.test.cjsx": "",
            },
            [
                ClassifiedSources(
                    JSXTestsGeneratorTarget,
                    ["UnownedFile1.test.jsx", "UnownedFile2.test.mjsx", "UnownedFile3.test.cjsx"],
                    "tests",
                )
            ],
            id="only_jsx_tests",
        ),
        pytest.param(
            {
                "src/owned/BUILD": "jsx_sources()\n",
                "src/owned/OwnedFile.jsx": "",
                "src/unowned/UnownedFile1.jsx": "",
                "src/unowned/UnownedFile1.test.jsx": "",
            },
            [
                ClassifiedSources(JSXTestsGeneratorTarget, ["UnownedFile1.test.jsx"], "tests"),
                ClassifiedSources(JSXSourcesGeneratorTarget, ["UnownedFile1.jsx"]),
            ],
            id="both_tests_and_source",
        ),
    ],
)
def test_find_putative_jsx_targets(
    rule_runner: RuleRunner, files: dict, putative_map: list[ClassifiedSources]
) -> None:
    rule_runner.write_files(files)
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeJSXTargetsRequest(("src/owned", "src/unowned")),
            AllOwnedSources(["src/owned/OwnedFile.jsx"]),
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
