# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.backend.typescript.goals import tailor
from pants.backend.typescript.goals.tailor import PutativeTypeScriptTargetsRequest
from pants.backend.typescript.target_types import (
    TypeScriptSourcesGeneratorTarget,
    TypeScriptTestsGeneratorTarget,
)
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.core.util_rules.source_files import ClassifiedSources
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeTypeScriptTargetsRequest, AllOwnedSources)),
        ],
        target_types=[TypeScriptSourcesGeneratorTarget],
    )


@pytest.mark.parametrize(
    "files,putative_map",
    [
        pytest.param(
            {
                "src/owned/BUILD": "typescript_sources()\n",
                "src/owned/OwnedFile.ts": "",
                "src/unowned/UnownedFile1.ts": "",
                "src/unowned/UnownedFile2.ts": "",
                "src/unowned/UnownedFile3.ts": "",
            },
            [
                ClassifiedSources(
                    TypeScriptSourcesGeneratorTarget,
                    ["UnownedFile1.ts", "UnownedFile2.ts", "UnownedFile3.ts"],
                )
            ],
            id="only_typescript_sources",
        ),
        pytest.param(
            {
                "src/owned/BUILD": "typescript_sources()\n",
                "src/owned/OwnedFile.ts": "",
                "src/unowned/UnownedFile1.test.ts": "",
                "src/unowned/UnownedFile2.test.ts": "",
                "src/unowned/UnownedFile3.test.ts": "",
            },
            [
                ClassifiedSources(
                    TypeScriptTestsGeneratorTarget,
                    ["UnownedFile1.test.ts", "UnownedFile2.test.ts", "UnownedFile3.test.ts"],
                    "tests",
                )
            ],
            id="only_typescript_tests",
        ),
        pytest.param(
            {
                "src/owned/BUILD": "typescript_sources()\n",
                "src/owned/OwnedFile.ts": "",
                "src/unowned/UnownedFile1.ts": "",
                "src/unowned/UnownedFile1.test.ts": "",
            },
            [
                ClassifiedSources(
                    TypeScriptTestsGeneratorTarget, ["UnownedFile1.test.ts"], "tests"
                ),
                ClassifiedSources(TypeScriptSourcesGeneratorTarget, ["UnownedFile1.ts"]),
            ],
            id="both_tests_and_source",
        ),
    ],
)
def test_find_putative_ts_targets(
    rule_runner: RuleRunner, files: dict, putative_map: list[ClassifiedSources]
) -> None:
    rule_runner.write_files(files)
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeTypeScriptTargetsRequest(("src/owned", "src/unowned")),
            AllOwnedSources(["src/owned/OwnedFile.ts"]),
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


@pytest.mark.parametrize(
    "files,putative_map",
    [
        pytest.param(
            {
                "src/owned/BUILD": "typescript_sources()\n",
                "src/owned/OwnedFile.ts": "",
                # sources have been tailored before; now need to tailor tests target
                "src/partially_unowned/BUILD": "typescript_sources()\n",
                "src/partially_unowned/OwnedFile.ts": "",
                "src/partially_unowned/UnownedFile.test.ts": "",
            },
            [
                ClassifiedSources(TypeScriptTestsGeneratorTarget, ["UnownedFile.test.ts"], "tests"),
            ],
            id="source_tailored_but_tests_are_not",
        ),
    ],
)
def test_find_putative_ts_targets_partially_owned(
    rule_runner: RuleRunner, files: dict, putative_map: list[ClassifiedSources]
) -> None:
    """Check that if `typescript_sources` target exist owning all `*.ts` files, the `.test.ts` files
    can still be tailored."""
    rule_runner.write_files(files)
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeTypeScriptTargetsRequest(("src/owned", "src/partially_unowned")),
            AllOwnedSources(["src/owned/OwnedFile.ts", "src/partially_unowned/OwnedFile.ts"]),
        ],
    )
    expected_targets = PutativeTargets(
        [
            PutativeTarget.for_target_type(
                source_class.target_type,
                "src/partially_unowned",
                source_class.name,
                source_class.files,
            )
            for source_class in putative_map
        ]
    )
    assert putative_targets == expected_targets
