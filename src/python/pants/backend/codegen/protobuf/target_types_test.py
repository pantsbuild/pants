# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.codegen.protobuf.target_types import (
    InjectProtobufDependencies,
    ProtobufDependencies,
    ProtobufLibrary,
)
from pants.backend.codegen.protobuf.target_types import rules as target_type_rules
from pants.core.target_types import Files
from pants.engine.addresses import Address
from pants.engine.target import InjectedDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_inject_dependencies() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_type_rules(),
            QueryRule(InjectedDependencies, (InjectProtobufDependencies,)),
        ],
        target_types=[ProtobufLibrary, Files],
    )
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.codegen.protobuf.python",
            "--protoc-runtime-targets=protos:injected_dep",
        ]
    )
    # Note that injected deps can be any target type for `--protobuf-runtime-targets`.
    rule_runner.add_to_build_file(
        "protos",
        dedent(
            """\
            protobuf_library()
            files(name="injected_dep", sources=[])
            """
        ),
    )
    tgt = rule_runner.get_target(Address("protos"))
    injected = rule_runner.request(
        InjectedDependencies, [InjectProtobufDependencies(tgt[ProtobufDependencies])]
    )
    assert injected == InjectedDependencies([Address("protos", target_name="injected_dep")])
