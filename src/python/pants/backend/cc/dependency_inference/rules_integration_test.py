# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

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


def test_dependency_inference(rule_runner: RuleRunner, caplog) -> None:
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
            "src/native/foo.h": dedent(
                """\
            extern void grok();
            """
            ),
            "src/native/foo.c": dedent(
                """\
            #include <stdio.h>
            void grok() {
              printf("grok!");
            }
            """
            ),
            # Test handling of ambiguous imports. We should warn on the ambiguous dependency, but
            # not warn on the disambiguated one and should infer a dep.
            "src/native/ambiguous/dep.h": "",
            "src/native/ambiguous/disambiguated.h": "",
            "src/native/ambiguous/main.c": dedent(
                """\
                #include "ambiguous/dep.h";
                #include "ambiguous/disambiguated.h";
                """
            ),
            "src/native/ambiguous/BUILD": dedent(
                """\
                cc_sources(name='dep1', sources=['dep.h', 'disambiguated.h'])
                cc_sources(name='dep2', sources=['dep.h', 'disambiguated.h'])
                cc_sources(
                    name='main',
                    sources=['main.c'],
                    dependencies=['!./disambiguated.h:dep2'],
                )
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

    caplog.clear()
    assert run_dep_inference(
        Address("src/native/ambiguous", target_name="main", relative_file_path="main.c")
    ) == InferredDependencies(
        [Address("src/native/ambiguous", target_name="dep1", relative_file_path="disambiguated.h")]
    )
    assert len(caplog.records) == 1
    assert "The target src/native/ambiguous/main.c:main includes `ambiguous/dep.h`" in caplog.text
    assert "['src/native/ambiguous/dep.h:dep1', 'src/native/ambiguous/dep.h:dep2']" in caplog.text
    assert "disambiguated.h" not in caplog.text
