# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.kotlin.goals import tailor
from pants.backend.kotlin.goals.tailor import PutativeKotlinTargetsRequest, classify_source_files
from pants.backend.kotlin.target_types import (
    KotlinJmhBenckmarksGeneratorTarget,
    KotlinJunitTestsGeneratorTarget,
    KotlinSourcesGeneratorTarget,
)
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeKotlinTargetsRequest, AllOwnedSources)),
        ],
        target_types=[KotlinSourcesGeneratorTarget],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/kotlin/owned/BUILD": "kotlin_sources()\n",
            "src/kotlin/owned/OwnedFile.kt": "package owned",
            "src/kotlin/unowned/UnownedFile.kt": "package unowned\n",
            "tests/kotlin/owned/BUILD": "kotlin_junit_tests()\n",
            "tests/kotlin/owned/OwnedTest.kt": "package owned",
            "tests/kotlin/unowned/UnownedTest.kt": "package unowned\n",
            "benches/kotlin/owned/BUILD": "kotlin_jmh_benchmarks()\n",
            "benches/kotlin/owned/OwnedBenchmark.kt": "package owned",
            "benches/kotlin/unowned/UnownedBenchmark.kt": "package unowned\n",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeKotlinTargetsRequest(
                (
                    "src/kotlin/owned",
                    "src/kotlin/unowned",
                    "tests/kotlin/owned",
                    "tests/kotlin/unowned",
                    "benches/kotlin/owned",
                    "benches/kotlin/unowned",
                )
            ),
            AllOwnedSources(
                [
                    "src/kotlin/owned/OwnedFile.kt",
                    "tests/kotlin/owned/OwnedTest.kt",
                    "benches/kotlin/owned/OwnedBenchmark.kt",
                ]
            ),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    KotlinSourcesGeneratorTarget,
                    "src/kotlin/unowned",
                    "unowned",
                    ["UnownedFile.kt"],
                ),
                PutativeTarget.for_target_type(
                    KotlinJmhBenckmarksGeneratorTarget,
                    "benches/kotlin/unowned",
                    "unowned",
                    ["UnownedBenchmark.kt"],
                ),
                PutativeTarget.for_target_type(
                    KotlinJunitTestsGeneratorTarget,
                    "tests/kotlin/unowned",
                    "unowned",
                    ["UnownedTest.kt"],
                ),
            ]
        )
        == putative_targets
    )


def test_classify_source_files() -> None:
    junit_files = {
        "foo/bar/BazTest.kt",
    }
    jmh_files = {
        "foo/bar/BazBenchmark.kt",
    }
    lib_files = {"foo/bar/Baz.kt"}

    assert {
        KotlinJunitTestsGeneratorTarget: junit_files,
        KotlinJmhBenckmarksGeneratorTarget: jmh_files,
        KotlinSourcesGeneratorTarget: lib_files,
    } == classify_source_files(junit_files | jmh_files | lib_files)
