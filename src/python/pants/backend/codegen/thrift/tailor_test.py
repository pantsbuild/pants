# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.codegen.thrift.tailor import PutativeThriftTargetsRequest
from pants.backend.codegen.thrift.tailor import rules as tailor_rules
from pants.backend.codegen.thrift.target_types import ThriftSourcesGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor_rules(),
            QueryRule(PutativeTargets, (PutativeThriftTargetsRequest, AllOwnedSources)),
        ],
        target_types=[],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "thrifts/foo/f.thrift": "",
            "thrifts/foo/bar/baz1.thrift": "",
            "thrifts/foo/bar/baz2.thrift": "",
            "thrifts/foo/bar/baz3.thrift": "",
        }
    )

    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeThriftTargetsRequest(("thrifts/foo", "thrifts/foo/bar")),
            AllOwnedSources(["thrifts/foo/bar/baz1.thrift"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    ThriftSourcesGeneratorTarget,
                    path="thrifts/foo",
                    name=None,
                    triggering_sources=["f.thrift"],
                ),
                PutativeTarget.for_target_type(
                    ThriftSourcesGeneratorTarget,
                    path="thrifts/foo/bar",
                    name=None,
                    triggering_sources=["baz2.thrift", "baz3.thrift"],
                ),
            ]
        )
        == pts
    )


def test_find_putative_targets_subset(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "thrifts/foo/f.thrift": "",
            "thrifts/foo/bar/bar.thrift": "",
            "thrifts/foo/baz/baz.thrift": "",
            "thrifts/foo/qux/qux.thrift": "",
        }
    )

    pts = rule_runner.request(
        PutativeTargets,
        [PutativeThriftTargetsRequest(("thrifts/foo/bar", "thrifts/foo/qux")), AllOwnedSources([])],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    ThriftSourcesGeneratorTarget,
                    path="thrifts/foo/bar",
                    name=None,
                    triggering_sources=["bar.thrift"],
                ),
                PutativeTarget.for_target_type(
                    ThriftSourcesGeneratorTarget,
                    path="thrifts/foo/qux",
                    name=None,
                    triggering_sources=["qux.thrift"],
                ),
            ]
        )
        == pts
    )
