# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.codegen.soap.tailor import PutativeWsdlTargetsRequest
from pants.backend.codegen.soap.tailor import rules as tailor_rules
from pants.backend.codegen.soap.target_types import WsdlSourcesGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor_rules(),
            QueryRule(PutativeTargets, (PutativeWsdlTargetsRequest, AllOwnedSources)),
        ],
        target_types=[],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/wsdl/simple.wsdl": "",
            "src/wsdl/dir1/hello.wsdl": "",
            "src/wsdl/dir1/world.wsdl": "",
        }
    )

    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeWsdlTargetsRequest(("src/wsdl", "src/wsdl/dir1")),
            AllOwnedSources(["src/wsdl/simple.wsdl"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    WsdlSourcesGeneratorTarget,
                    path="src/wsdl/dir1",
                    name=None,
                    triggering_sources=["hello.wsdl", "world.wsdl"],
                ),
            ]
        )
        == pts
    )
