# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.codegen.protobuf.tailor import PutativeProtobufTargetsRequest
from pants.backend.codegen.protobuf.tailor import rules as tailor_rules
from pants.backend.codegen.protobuf.target_types import ProtobufSourcesGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor_rules(),
            QueryRule(PutativeTargets, (PutativeProtobufTargetsRequest, AllOwnedSources)),
        ],
        target_types=[],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "protos/foo/f.proto": "",
            "protos/foo/bar/baz1.proto": "",
            "protos/foo/bar/baz2.proto": "",
            "protos/foo/bar/baz3.proto": "",
        }
    )

    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeProtobufTargetsRequest(("protos/foo", "protos/foo/bar")),
            AllOwnedSources(["protos/foo/bar/baz1.proto"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    ProtobufSourcesGeneratorTarget,
                    path="protos/foo",
                    name=None,
                    triggering_sources=["f.proto"],
                ),
                PutativeTarget.for_target_type(
                    ProtobufSourcesGeneratorTarget,
                    path="protos/foo/bar",
                    name=None,
                    triggering_sources=["baz2.proto", "baz3.proto"],
                ),
            ]
        )
        == pts
    )


def test_find_putative_targets_subset(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "protos/foo/f.proto": "",
            "protos/foo/bar/bar.proto": "",
            "protos/foo/baz/baz.proto": "",
            "protos/foo/qux/qux.proto": "",
        }
    )

    pts = rule_runner.request(
        PutativeTargets,
        [PutativeProtobufTargetsRequest(("protos/foo/bar", "protos/foo/qux")), AllOwnedSources([])],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    ProtobufSourcesGeneratorTarget,
                    path="protos/foo/bar",
                    name=None,
                    triggering_sources=["bar.proto"],
                ),
                PutativeTarget.for_target_type(
                    ProtobufSourcesGeneratorTarget,
                    path="protos/foo/qux",
                    name=None,
                    triggering_sources=["qux.proto"],
                ),
            ]
        )
        == pts
    )
