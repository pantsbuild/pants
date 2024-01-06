# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.java.goals import tailor
from pants.backend.java.goals.tailor import PutativeJavaTargetsRequest, classify_source_files
from pants.backend.java.target_types import (
    JavaSourcesGeneratorTarget,
    JmhBenckmarksGeneratorTarget,
    JunitTestsGeneratorTarget,
)
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_classify_source_files() -> None:
    test_files = {
        "foo/bar/BazTest.java",
    }
    benchmark_files = {
        "foo/bar/BazBenchmark.java",
    }
    lib_files = {"foo/bar/Baz.java", "foo/SomeClass.java"}

    assert {
        JunitTestsGeneratorTarget: test_files,
        JmhBenckmarksGeneratorTarget: benchmark_files,
        JavaSourcesGeneratorTarget: lib_files,
    } == classify_source_files(test_files | benchmark_files | lib_files)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeJavaTargetsRequest, AllOwnedSources)),
        ],
        target_types=[JavaSourcesGeneratorTarget, JunitTestsGeneratorTarget],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/java/owned/BUILD": "java_sources()\n",
            "src/java/owned/OwnedFile.java": "package owned",
            "src/java/unowned/UnownedFile.java": "package unowned\n",
            "src/java/unowned/UnownedFileTest.java": "package unowned\n",
            "src/java/unowned/UnownedFileBenchmark.java": "package unowned\n",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeJavaTargetsRequest(("src/java", "src/java/unowned")),
            AllOwnedSources(["src/java/owned/OwnedFile.java"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    JavaSourcesGeneratorTarget, "src/java/unowned", "unowned", ["UnownedFile.java"]
                ),
                PutativeTarget.for_target_type(
                    JunitTestsGeneratorTarget,
                    "src/java/unowned",
                    "tests",
                    ["UnownedFileTest.java"],
                ),
                PutativeTarget.for_target_type(
                    JmhBenckmarksGeneratorTarget,
                    "src/java/unowned",
                    "unowned",
                    ["UnownedFileBenchmark.java"],
                ),
            ]
        )
        == putative_targets
    )
