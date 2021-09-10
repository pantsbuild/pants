# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.java import tailor
from pants.backend.java.tailor import PutativeJavaTargetsRequest, classify_source_files
from pants.backend.java.target_types import JavaLibrary, JunitTests
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsSearchPaths,
)
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_classify_source_files() -> None:
    test_files = {
        "foo/bar/BazTest.java",
    }
    lib_files = {"foo/bar/Baz.java", "foo/SomeClass.java"}

    assert {JunitTests: test_files, JavaLibrary: lib_files} == classify_source_files(
        test_files | lib_files
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeJavaTargetsRequest, AllOwnedSources)),
        ],
        target_types=[JavaLibrary, JunitTests],
    )
    rule_runner.set_options(["--backend-packages=pants.backend.experimental.java"])
    return rule_runner


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/java/owned/BUILD": "java_library()\n",
            "src/java/owned/OwnedFile.java": "package owned",
            "src/java/unowned/UnownedFile.java": "package unowned\n",
            "src/java/unowned/UnownedFileTest.java": "package unowned\n",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeJavaTargetsRequest(PutativeTargetsSearchPaths(("",))),
            AllOwnedSources(["src/java/owned/OwnedFile.java"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    JavaLibrary, "src/java/unowned", "unowned", ["UnownedFile.java"]
                ),
                PutativeTarget.for_target_type(
                    JunitTests,
                    "src/java/unowned",
                    "tests",
                    ["UnownedFileTest.java"],
                    kwargs={"name": "tests"},
                ),
            ]
        )
        == putative_targets
    )
