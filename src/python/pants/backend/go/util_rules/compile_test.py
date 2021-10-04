# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go.util_rules import compile, sdk
from pants.backend.go.util_rules.compile import CompiledGoSources, CompileGoSourcesRequest
from pants.engine.fs import Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *compile.rules(),
            QueryRule(CompiledGoSources, [CompileGoSourcesRequest]),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_compile_simple_source_file(rule_runner: RuleRunner) -> None:
    digest = rule_runner.make_snapshot(
        {
            "foo.go": dedent(
                """\
                package foo
                func add(a, b int) int {
                    return a + b
                }
                """
            )
        }
    ).digest
    result = rule_runner.request(
        CompiledGoSources,
        [
            CompileGoSourcesRequest(
                digest=digest,
                sources=("foo.go",),
                import_path="foo",
                description="test_compile_simple_source_file",
            )
        ],
    )
    snapshot = rule_runner.request(Snapshot, [result.output_digest])
    assert "__pkg__.a" in snapshot.files
    assert not snapshot.dirs
