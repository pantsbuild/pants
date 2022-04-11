# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.cc.dependency_inference.rules import InferCCDependenciesRequest
from pants.backend.cc.dependency_inference.rules import rules as cc_dep_inf_rules
from pants.backend.cc.target_types import CCSourceField, CCSourcesGeneratorTarget, CCSourceTarget
from pants.backend.cc.target_types import rules as target_type_rules
from pants.build_graph.address import Address
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import RuleRunner
from pants.util.strutil import softwrap


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *cc_dep_inf_rules(),
            *target_type_rules(),
        ],
        target_types=[
            CCSourceTarget,
            CCSourcesGeneratorTarget,
        ],
    )


def test_dependency_inference(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--source-root-patterns=['src/native']"])
    rule_runner.write_files(
        {
            "src/native/BUILD": "cc_sources()",
            "src/native/main.c": softwrap(
                """\
            #include "foo.h"
            int main() {}
            """
            ),
            "src/native/foo.h": softwrap(
                """\
            extern void grok();
            """
            ),
            "src/native/foo.c": softwrap(
                """\
            #include <stdio.h>
            void grok() {
              printf("grok!");
            }
            """
            ),
        }
    )

    def run_dep_inference(address: Address) -> InferredDependencies:
        tgt = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies, [InferCCDependenciesRequest(tgt[CCSourceField])]
        )

    assert run_dep_inference(
        Address("src/native", relative_file_path="main.c")
    ) == InferredDependencies([Address("src/native", relative_file_path="foo.h")])
    assert run_dep_inference(
        Address("src/native", relative_file_path="foo.h")
    ) == InferredDependencies([])
    assert run_dep_inference(
        Address("src/native", relative_file_path="foo.c")
    ) == InferredDependencies([])
