# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.backend.kotlin.compile import kotlinc_plugins
from pants.backend.kotlin.compile.kotlinc import rules as kotlinc_rules
from pants.backend.kotlin.lint.ktlint import rules as ktlint_fmt_rules
from pants.backend.kotlin.lint.ktlint import skip_field
from pants.backend.kotlin.lint.ktlint.rules import KtlintFieldSet, KtlintRequest
from pants.backend.kotlin.target_types import KotlinSourcesGeneratorTarget, KotlinSourceTarget
from pants.backend.kotlin.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import config_files, source_files, system_binaries
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.jvm import classpath, jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *classpath.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *jdk_rules.rules(),
            *strip_jar.rules(),
            *kotlinc_rules(),
            *kotlinc_plugins.rules(),
            *util_rules(),
            *target_types_rules(),
            *ktlint_fmt_rules.rules(),
            *skip_field.rules(),
            *system_binaries.rules(),
            *source_files.rules(),
            QueryRule(FmtResult, (KtlintRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[KotlinSourceTarget, KotlinSourcesGeneratorTarget],
    )
    rule_runner.set_options(
        [],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


GOOD_FILE = """\
package org.pantsbuild.example

open class Foo {
    val CONSTANT = "Constant changes"
}
"""

BAD_FILE = """\
package org.pantsbuild.example

open class Bar {
val CONSTANT = "Constant changes"
}
"""

FIXED_BAD_FILE = """\
package org.pantsbuild.example

open class Bar {
    val CONSTANT = "Constant changes"
}
"""


def run_ktlint(rule_runner: RuleRunner, targets: list[Target]) -> FmtResult:
    field_sets = [KtlintFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.source for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            KtlintRequest.Batch(
                "",
                input_sources.snapshot.files,
                partition_metadata=None,
                snapshot=input_sources.snapshot,
            ),
        ],
    )
    return fmt_result


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"Foo.kt": GOOD_FILE, "BUILD": "kotlin_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="Foo.kt"))
    fmt_result = run_ktlint(rule_runner, [tgt])
    assert fmt_result.output == rule_runner.make_snapshot({"Foo.kt": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"Bar.kt": BAD_FILE, "BUILD": "kotlin_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="Bar.kt"))
    fmt_result = run_ktlint(rule_runner, [tgt])
    assert fmt_result.output == rule_runner.make_snapshot({"Bar.kt": FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"Foo.kt": GOOD_FILE, "Bar.kt": BAD_FILE, "BUILD": "kotlin_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="Foo.kt")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="Bar.kt")),
    ]
    fmt_result = run_ktlint(rule_runner, tgts)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"Foo.kt": GOOD_FILE, "Bar.kt": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True
