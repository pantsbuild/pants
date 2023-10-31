# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

from pants.backend.codegen.protobuf import target_types
from pants.backend.codegen.protobuf.python import additional_fields, python_protobuf_subsystem
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    InferPythonProtobufDependencies,
    PythonProtobufDependenciesInferenceFieldSet,
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
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


def test_find_protobuf_python_requirement() -> None:
    rule_runner = RuleRunner(
        rules=[
            *python_protobuf_subsystem.rules(),
            *target_types.rules(),
            *module_mapper.rules(),
            *stripped_source_files.rules(),
            *additional_fields.rules(),
            QueryRule(InferredDependencies, (InferPythonProtobufDependencies,)),
        ],
        target_types=[ProtobufSourcesGeneratorTarget, PythonRequirementTarget],
    )

    rule_runner.write_files(
        {"codegen/dir/f.proto": "", "codegen/dir/BUILD": "protobuf_sources(grpc=True)"}
    )
    rule_runner.set_options(
        [
            "--python-resolves={'python-default': '', 'another': ''}",
            "--python-enable-resolves",
            # Turn off python synthetic lockfile targets to make the test simpler.
            "--no-python-enable-lockfile-targets",
        ]
    )
    proto_tgt = rule_runner.get_target(Address("codegen/dir", relative_file_path="f.proto"))
    request = InferPythonProtobufDependencies(
        PythonProtobufDependenciesInferenceFieldSet.create(proto_tgt)
    )

    # Start with no relevant requirements.
    with engine_error(MissingPythonCodegenRuntimeLibrary, contains="protobuf"):
        rule_runner.request(InferredDependencies, [request])
    rule_runner.write_files({"proto1/BUILD": "python_requirement(requirements=['protobuf'])"})
    with engine_error(MissingPythonCodegenRuntimeLibrary, contains="grpcio"):
        rule_runner.request(InferredDependencies, [request])

    # If exactly one, match it.
    rule_runner.write_files({"grpc1/BUILD": "python_requirement(requirements=['grpc'])"})
    assert rule_runner.request(InferredDependencies, [request]) == InferredDependencies(
        [Address("proto1"), Address("grpc1")]
    )

    # Multiple is fine if from other resolve.
    rule_runner.write_files(
        {
            "another_resolve/BUILD": dedent(
                """\
                python_requirement(name='r1', requirements=['protobuf'], resolve='another')
                python_requirement(name='r2', requirements=['grpc'], resolve='another')
                """
            )
        }
    )
    assert rule_runner.request(InferredDependencies, [request]) == InferredDependencies(
        [Address("proto1"), Address("grpc1")]
    )

    # If multiple from the same resolve, error.
    rule_runner.write_files(
        {"codegen/dir/grpc2/BUILD": "python_requirement(requirements=['grpc'])"}
    )
    with engine_error(
        AmbiguousPythonCodegenRuntimeLibrary, contains="['codegen/dir/grpc2:grpc2', 'grpc1:grpc1']"
    ):
        rule_runner.request(InferredDependencies, [request])
    rule_runner.write_files(
        {"codegen/dir/proto2/BUILD": "python_requirement(requirements=['protobuf'])"}
    )
    with engine_error(
        AmbiguousPythonCodegenRuntimeLibrary,
        contains="['codegen/dir/proto2:proto2', 'proto1:proto1']",
    ):
        rule_runner.request(InferredDependencies, [request])

    # If multiple from the same resolve, error unless locality is enabled.
    rule_runner.set_options(
        [
            "--python-resolves={'python-default': '', 'another': ''}",
            "--python-enable-resolves",
            # Turn off python synthetic lockfile targets to make the test simpler.
            "--no-python-enable-lockfile-targets",
            "--python-infer-ambiguity-resolution=by_source_root",
            "--source-root-patterns=['codegen/dir']",
        ]
    )

    assert rule_runner.request(InferredDependencies, [request]) == InferredDependencies(
        [Address("codegen/dir/grpc2"), Address("codegen/dir/proto2")]
    )
