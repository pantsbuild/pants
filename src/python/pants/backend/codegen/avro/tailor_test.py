# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.codegen.avro.tailor import PutativeAvroTargetsRequest
from pants.backend.codegen.avro.tailor import rules as tailor_rules
from pants.backend.codegen.avro.target_types import AvroSourcesGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor_rules(),
            QueryRule(PutativeTargets, (PutativeAvroTargetsRequest, AllOwnedSources)),
        ],
        target_types=[],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "avro/foo/f.avsc": "",
            "avro/foo/bar/baz1.avdl": "",
            "avro/foo/bar/baz2.avpr": "",
            "avro/foo/bar/baz3.avsc": "",
        }
    )

    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeAvroTargetsRequest(("avro/foo", "avro/foo/bar")),
            AllOwnedSources(["avro/foo/bar/baz1.avdl"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    AvroSourcesGeneratorTarget,
                    path="avro/foo",
                    name=None,
                    triggering_sources=["f.avsc"],
                ),
                PutativeTarget.for_target_type(
                    AvroSourcesGeneratorTarget,
                    path="avro/foo/bar",
                    name=None,
                    triggering_sources=["baz2.avpr", "baz3.avsc"],
                ),
            ]
        )
        == pts
    )


def test_find_putative_targets_subset(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "avro/foo/f.avsc": "",
            "avro/foo/bar/bar.avsc": "",
            "avro/foo/baz/baz.avsc": "",
            "avro/foo/qux/qux.avsc": "",
        }
    )

    pts = rule_runner.request(
        PutativeTargets,
        [PutativeAvroTargetsRequest(("avro/foo/bar", "avro/foo/qux")), AllOwnedSources([])],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    AvroSourcesGeneratorTarget,
                    path="avro/foo/bar",
                    name=None,
                    triggering_sources=["bar.avsc"],
                ),
                PutativeTarget.for_target_type(
                    AvroSourcesGeneratorTarget,
                    path="avro/foo/qux",
                    name=None,
                    triggering_sources=["qux.avsc"],
                ),
            ]
        )
        == pts
    )
