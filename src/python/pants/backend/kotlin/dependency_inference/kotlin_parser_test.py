# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap

import pytest

from pants.backend.kotlin import target_types
from pants.backend.kotlin.dependency_inference import kotlin_parser
from pants.backend.kotlin.dependency_inference.kotlin_parser import (
    KotlinImport,
    KotlinSourceDependencyAnalysis,
)
from pants.backend.kotlin.target_types import KotlinSourceField, KotlinSourceTarget
from pants.build_graph.address import Address
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.rules import QueryRule
from pants.engine.target import SourcesField
from pants.jvm import jdk_rules
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.resolve import jvm_tool
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner, logging
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *kotlin_parser.rules(),
            *jvm_tool.rules(),
            *source_files.rules(),
            *jdk_rules.rules(),
            *target_types.rules(),
            *jvm_util_rules.rules(),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
            QueryRule(KotlinSourceDependencyAnalysis, (SourceFiles,)),
        ],
        target_types=[KotlinSourceTarget],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def _analyze(rule_runner: RuleRunner, source: str) -> KotlinSourceDependencyAnalysis:
    rule_runner.write_files(
        {
            "BUILD": """kotlin_source(name="source", source="Source.kt")""",
            "Source.kt": source,
        }
    )

    target = rule_runner.get_target(address=Address("", target_name="source"))

    source_files = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(
                (target.get(SourcesField),),
                for_sources_types=(KotlinSourceField,),
                enable_codegen=True,
            )
        ],
    )

    return rule_runner.request(KotlinSourceDependencyAnalysis, [source_files])


@logging
@pytest.mark.platform_specific_behavior
def test_parser_simple(rule_runner: RuleRunner) -> None:
    analysis = _analyze(
        rule_runner,
        textwrap.dedent(
            """\
            package org.pantsbuild.backend.kotlin

            import java.io.File

            open class Foo {
              fun grok() {
                val x = X()
                val y = Y()
              }
            }

            class Bar {}

            fun main(args: Array<String>) {
            }
            """
        ),
    )

    assert analysis.imports == {KotlinImport(name="java.io.File", alias=None, is_wildcard=False)}
    assert analysis.named_declarations == {
        "org.pantsbuild.backend.kotlin.Bar",
        "org.pantsbuild.backend.kotlin.Foo",
        "org.pantsbuild.backend.kotlin.main",
    }
    assert analysis.consumed_symbols_by_scope == FrozenDict(
        {
            "org.pantsbuild.backend.kotlin.Foo": frozenset(
                {
                    "X",
                    "Y",
                }
            ),
            "org.pantsbuild.backend.kotlin": frozenset(
                {
                    "Array",
                    "String",
                }
            ),
        }
    )
    assert analysis.scopes == {
        "org.pantsbuild.backend.kotlin",
        "org.pantsbuild.backend.kotlin.Foo",
        "org.pantsbuild.backend.kotlin.Bar",
    }
