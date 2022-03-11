# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen.protobuf import target_types
from pants.backend.codegen.protobuf.python import python_protobuf_subsystem
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    InjectPythonProtobufDependencies,
)
from pants.backend.codegen.protobuf.target_types import ProtobufSourcesGeneratorTarget
from pants.backend.codegen.utils import (
    AmbiguousPythonCodegenRuntimeLibrary,
    MissingPythonCodegenRuntimeLibrary,
)
from pants.backend.python.dependency_inference import module_mapper
from pants.backend.python.target_types import PythonRequirementTarget
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.target import Dependencies, InjectedDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


def test_find_protobuf_python_requirement() -> None:
    rule_runner = RuleRunner(
        rules=[
            *python_protobuf_subsystem.rules(),
            *target_types.rules(),
            *module_mapper.rules(),
            *stripped_source_files.rules(),
            QueryRule(InjectedDependencies, (InjectPythonProtobufDependencies,)),
        ],
        target_types=[ProtobufSourcesGeneratorTarget, PythonRequirementTarget],
    )

    rule_runner.write_files(
        {"codegen/dir/f.proto": "", "codegen/dir/BUILD": "protobuf_sources(grpc=True)"}
    )
    rule_runner.set_options(
        ["--python-resolves={'python-default': '', 'another': ''}", "--python-enable-resolves"]
    )
    proto_tgt = rule_runner.get_target(Address("codegen/dir", relative_file_path="f.proto"))
    request = InjectPythonProtobufDependencies(proto_tgt[Dependencies])

    # Start with no relevant requirements.
    with engine_error(MissingPythonCodegenRuntimeLibrary, contains="protobuf"):
        rule_runner.request(InjectedDependencies, [request])
    rule_runner.write_files({"proto1/BUILD": "python_requirement(requirements=['protobuf'])"})
    with engine_error(MissingPythonCodegenRuntimeLibrary, contains="grpcio"):
        rule_runner.request(InjectedDependencies, [request])

    # If exactly one, match it.
    rule_runner.write_files({"grpc1/BUILD": "python_requirement(requirements=['grpc'])"})
    assert rule_runner.request(InjectedDependencies, [request]) == InjectedDependencies(
        [Address("proto1"), Address("grpc1")]
    )

    # Multiple is fine if from other resolve.
    rule_runner.write_files(
        {
            "another_resolve/BUILD": (
                "python_requirement(name='r1', requirements=['protobuf'], resolve='another')\n"
                "python_requirement(name='r2', requirements=['grpc'], resolve='another')\n"
            )
        }
    )
    assert rule_runner.request(InjectedDependencies, [request]) == InjectedDependencies(
        [Address("proto1"), Address("grpc1")]
    )

    # If multiple from the same resolve, error.
    rule_runner.write_files({"grpc2/BUILD": "python_requirement(requirements=['grpc'])"})
    with engine_error(
        AmbiguousPythonCodegenRuntimeLibrary, contains="['grpc1:grpc1', 'grpc2:grpc2']"
    ):
        rule_runner.request(InjectedDependencies, [request])
    rule_runner.write_files({"proto2/BUILD": "python_requirement(requirements=['protobuf'])"})
    with engine_error(
        AmbiguousPythonCodegenRuntimeLibrary, contains="['proto1:proto1', 'proto2:proto2']"
    ):
        rule_runner.request(InjectedDependencies, [request])
