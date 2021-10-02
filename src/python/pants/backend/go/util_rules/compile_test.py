# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap

import pytest

from pants.backend.go.target_types import GoModTarget, GoPackage
from pants.backend.go.util_rules import compile, sdk
from pants.backend.go.util_rules.compile import CompiledGoSources, CompileGoSourcesRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner

SOURCE = FileContent(
    path="foo.go",
    content=textwrap.dedent(
        """\
        package foo
        func add(a, b int) int {
            return a + b
        }
        """
    ).encode("utf-8"),
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            # *source_files.rules(),
            *sdk.rules(),
            *compile.rules(),
            QueryRule(Digest, [CreateDigest]),
            QueryRule(Snapshot, [Digest]),
            QueryRule(CompiledGoSources, [CompileGoSourcesRequest]),
        ],
        target_types=[GoPackage, GoModTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_compile_simple_source_file(rule_runner: RuleRunner) -> None:
    sources_digest = rule_runner.request(Digest, [CreateDigest([SOURCE])])

    result = rule_runner.request(
        CompiledGoSources,
        [
            CompileGoSourcesRequest(
                digest=sources_digest,
                sources=(SOURCE.path,),
                import_path="foo",
                description="test_compile_simple_source_file",
            )
        ],
    )

    snapshot = rule_runner.request(Snapshot, [result.output_digest])
    assert "__pkg__.a" in snapshot.files
    assert not snapshot.dirs
