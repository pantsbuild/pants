# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.backend.tsx.goals import tailor
from pants.backend.tsx.goals.tailor import PutativeTSXTargetsRequest
from pants.backend.tsx.target_types import TSXSourcesGeneratorTarget, TSXTestsGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.core.util_rules.source_files import ClassifiedSources
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeTSXTargetsRequest, AllOwnedSources)),
        ],
        target_types=[TSXTestsGeneratorTarget, TSXSourcesGeneratorTarget],
    )


@pytest.mark.parametrize(
    "files,putative_map",
    [
        pytest.param(
            {
                "src/owned/BUILD": "typescript_sources()\n",
                "src/owned/OwnedFile.tsx": "",
                "src/unowned/UnownedFile1.tsx": "",
            },
            [
                ClassifiedSources(
                    TSXSourcesGeneratorTarget,
                    ["UnownedFile1.tsx"],
                )
            ],
            id="only_tsx_sources",
        ),
        pytest.param(
            {
                "src/owned/BUILD": "tsx_sources()\n",
                "src/owned/OwnedFile.tsx": "",
                "src/unowned/UnownedFile1.test.tsx": "",
            },
            [
                ClassifiedSources(
                    TSXTestsGeneratorTarget,
                    ["UnownedFile1.test.tsx"],
                    "tests",
                )
            ],
            id="only_tsx_tests",
        ),
        pytest.param(
            {
                "src/owned/BUILD": "tsx_sources()\n",
                "src/owned/OwnedFile.tsx": "",
                "src/unowned/UnownedFile1.tsx": "",
                "src/unowned/UnownedFile1.test.tsx": "",
            },
            [
                ClassifiedSources(TSXTestsGeneratorTarget, ["UnownedFile1.test.tsx"], "tests"),
                ClassifiedSources(TSXSourcesGeneratorTarget, ["UnownedFile1.tsx"]),
            ],
            id="both_tests_and_source",
        ),
    ],
)
def test_find_putative_tsx_targets(
    rule_runner: RuleRunner, files: dict, putative_map: list[ClassifiedSources]
) -> None:
    rule_runner.write_files(files)
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeTSXTargetsRequest(("src/owned", "src/unowned")),
            AllOwnedSources(["src/owned/OwnedFile.tsx"]),
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
