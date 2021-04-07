# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.tailor import PutativeProtobufTargetsRequest
from pants.backend.codegen.protobuf.tailor import rules as tailor_rules
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_find_putative_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            *tailor_rules(),
            QueryRule(PutativeTargets, (PutativeProtobufTargetsRequest, AllOwnedSources)),
        ],
        target_types=[],
    )
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
        [PutativeProtobufTargetsRequest(), AllOwnedSources(["protos/foo/bar/baz1.proto"])],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(ProtobufLibrary, "protos/foo", "foo", ["f.proto"]),
                PutativeTarget.for_target_type(
                    ProtobufLibrary, "protos/foo/bar", "bar", ["baz2.proto", "baz3.proto"]
                ),
            ]
        )
        == pts
    )
