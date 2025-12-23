# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.codegen.protobuf import protobuf_dependency_inference
from pants.backend.codegen.protobuf.protobuf_dependency_inference import (
    InferProtobufDependencies,
    ProtobufMapping,
)
from pants.backend.codegen.protobuf.python import additional_fields
from pants.backend.codegen.protobuf.target_types import ProtobufSourcesGeneratorTarget
from pants.backend.codegen.protobuf.target_types import rules as target_types_rules
from pants.backend.python import target_types_rules as python_target_types_rules
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner_with_python_resolves() -> RuleRunner:
    """Rule runner with Python resolve support for testing multi-resolve scenarios."""
    return RuleRunner(
        rules=[
            *stripped_source_files.rules(),
            *protobuf_dependency_inference.rules(),
            *target_types_rules(),
            *additional_fields.rules(),
            *python_target_types_rules.rules(),
            QueryRule(ProtobufMapping, []),
            QueryRule(InferredDependencies, [InferProtobufDependencies]),
        ],
        target_types=[ProtobufSourcesGeneratorTarget],
    )


def test_protobuf_mapping_with_single_resolve(rule_runner_with_python_resolves: RuleRunner) -> None:
    """Verify that when all protobuf targets use the same resolve, they are correctly grouped."""
    rule_runner_with_python_resolves.set_options(
        [
            "--source-root-patterns=['protos']",
            "--python-enable-resolves",
            "--python-resolves={'python-default': ''}",
        ]
    )
    rule_runner_with_python_resolves.write_files(
        {
            "protos/a.proto": "",
            "protos/b.proto": "",
            "protos/BUILD": "protobuf_sources(python_resolve='python-default')",
        }
    )
    result = rule_runner_with_python_resolves.request(ProtobufMapping, [])

    # Assert only one resolve key exists
    assert len(result.mapping) == 1

    # Get the resolve key
    resolve_key = list(result.mapping.keys())[0]
    assert resolve_key.resolve == "python-default"

    # Assert both files are in the mapping
    mapping = result.mapping[resolve_key]
    assert "a.proto" in mapping
    assert "b.proto" in mapping
    assert mapping["a.proto"] == Address("protos", relative_file_path="a.proto")
    assert mapping["b.proto"] == Address("protos", relative_file_path="b.proto")


def test_protobuf_mapping_with_multiple_resolves(
    rule_runner_with_python_resolves: RuleRunner,
) -> None:
    """Verify correct partitioning when targets use different resolves."""
    rule_runner_with_python_resolves.set_options(
        [
            "--source-root-patterns=['protos']",
            "--python-enable-resolves",
            "--python-resolves={'prod': '', 'dev': ''}",
        ]
    )
    rule_runner_with_python_resolves.write_files(
        {
            "protos/prod/service.proto": "",
            "protos/prod/BUILD": "protobuf_sources(python_resolve='prod')",
            "protos/dev/service.proto": "",  # Same name, different resolve
            "protos/dev/BUILD": "protobuf_sources(python_resolve='dev')",
        }
    )
    result = rule_runner_with_python_resolves.request(ProtobufMapping, [])

    # Assert two resolve keys exist
    assert len(result.mapping) == 2

    # Find the resolve keys
    resolve_keys = {key.resolve: key for key in result.mapping.keys()}
    assert "prod" in resolve_keys
    assert "dev" in resolve_keys

    # Assert each resolve has its own mapping
    prod_mapping = result.mapping[resolve_keys["prod"]]
    dev_mapping = result.mapping[resolve_keys["dev"]]

    # Assert files in prod resolve map to prod targets only
    assert "prod/service.proto" in prod_mapping
    assert prod_mapping["prod/service.proto"] == Address(
        "protos/prod", relative_file_path="service.proto"
    )

    # Assert files in dev resolve map to dev targets only
    assert "dev/service.proto" in dev_mapping
    assert dev_mapping["dev/service.proto"] == Address(
        "protos/dev", relative_file_path="service.proto"
    )

    # Assert no cross-contamination
    assert "dev/service.proto" not in prod_mapping
    assert "prod/service.proto" not in dev_mapping


def test_dependency_inference_within_resolve(rule_runner_with_python_resolves: RuleRunner) -> None:
    """Verify that dependency inference only finds dependencies within the same resolve."""
    rule_runner_with_python_resolves.set_options(
        [
            "--source-root-patterns=['protos/resolve_a', 'protos/resolve_b']",
            "--python-enable-resolves",
            "--python-resolves={'resolve-a': '', 'resolve-b': ''}",
        ]
    )
    rule_runner_with_python_resolves.write_files(
        {
            "protos/resolve_a/a.proto": "import 'b.proto';",
            "protos/resolve_a/b.proto": "",
            "protos/resolve_a/BUILD": "protobuf_sources(python_resolve='resolve-a')",
            "protos/resolve_b/a.proto": "import 'b.proto';",
            "protos/resolve_b/b.proto": "",
            "protos/resolve_b/BUILD": "protobuf_sources(python_resolve='resolve-b')",
        }
    )

    def run_dep_inference(address: Address) -> InferredDependencies:
        tgt = rule_runner_with_python_resolves.get_target(address)
        return rule_runner_with_python_resolves.request(
            InferredDependencies,
            [InferProtobufDependencies(ProtobufDependencyInferenceFieldSet.create(tgt))],
        )

    # Test inference for resolve-a
    deps_a = run_dep_inference(Address("protos/resolve_a", relative_file_path="a.proto"))
    assert deps_a == InferredDependencies(
        [Address("protos/resolve_a", relative_file_path="b.proto")]
    )

    # Test inference for resolve-b
    deps_b = run_dep_inference(Address("protos/resolve_b", relative_file_path="a.proto"))
    assert deps_b == InferredDependencies(
        [Address("protos/resolve_b", relative_file_path="b.proto")]
    )


def test_dependency_inference_no_cross_resolve(
    rule_runner_with_python_resolves: RuleRunner,
) -> None:
    """Verify that imports cannot be resolved across different resolves."""
    rule_runner_with_python_resolves.set_options(
        [
            "--source-root-patterns=['protos']",
            "--python-enable-resolves",
            "--python-resolves={'resolve-a': '', 'resolve-b': ''}",
        ]
    )
    rule_runner_with_python_resolves.write_files(
        {
            "protos/a/main.proto": "import 'common.proto';",
            "protos/a/BUILD": "protobuf_sources(python_resolve='resolve-a')",
            "protos/b/common.proto": "",
            "protos/b/BUILD": "protobuf_sources(python_resolve='resolve-b')",
        }
    )

    def run_dep_inference(address: Address) -> InferredDependencies:
        tgt = rule_runner_with_python_resolves.get_target(address)
        return rule_runner_with_python_resolves.request(
            InferredDependencies,
            [InferProtobufDependencies(ProtobufDependencyInferenceFieldSet.create(tgt))],
        )

    deps = run_dep_inference(Address("protos/a", relative_file_path="main.proto"))
    # Should be empty since common.proto is in different resolve
    assert deps == InferredDependencies([])


def test_ambiguous_imports_within_resolve(
    rule_runner_with_python_resolves: RuleRunner, caplog
) -> None:
    """Verify that ambiguous proto file names within a single resolve are handled correctly."""
    rule_runner_with_python_resolves.set_options(
        [
            "--source-root-patterns=['root/*']",
            "--python-enable-resolves",
            "--python-resolves={'prod': ''}",
        ]
    )
    rule_runner_with_python_resolves.write_files(
        {
            "root/loc1/common.proto": "",
            "root/loc1/BUILD": "protobuf_sources(name='common1', python_resolve='prod')",
            "root/loc2/common.proto": "",
            "root/loc2/BUILD": "protobuf_sources(name='common2', python_resolve='prod')",
            "root/loc3/main.proto": "import 'common.proto';",
            "root/loc3/BUILD": "protobuf_sources(name='main', python_resolve='prod')",
        }
    )

    # Check that both are marked as ambiguous
    result = rule_runner_with_python_resolves.request(ProtobufMapping, [])

    # Find the prod resolve key
    prod_key = [key for key in result.ambiguous_modules.keys() if key.resolve == "prod"][0]

    # Assert ambiguous_modules contains the conflict
    assert "common.proto" in result.ambiguous_modules[prod_key]
    ambiguous_addrs = result.ambiguous_modules[prod_key]["common.proto"]
    assert len(ambiguous_addrs) == 2
    assert (
        Address("root/loc1", target_name="common1", relative_file_path="common.proto")
        in ambiguous_addrs
    )
    assert (
        Address("root/loc2", target_name="common2", relative_file_path="common.proto")
        in ambiguous_addrs
    )

    # Test dependency inference warns
    def run_dep_inference(address: Address) -> InferredDependencies:
        tgt = rule_runner_with_python_resolves.get_target(address)
        return rule_runner_with_python_resolves.request(
            InferredDependencies,
            [InferProtobufDependencies(ProtobufDependencyInferenceFieldSet.create(tgt))],
        )

    caplog.clear()
    run_dep_inference(Address("root/loc3", target_name="main", relative_file_path="main.proto"))
    assert "ambiguous" in caplog.text.lower()


def test_ambiguous_imports_across_resolves_ok(
    rule_runner_with_python_resolves: RuleRunner, caplog
) -> None:
    """Verify that the same proto file name in different resolves does NOT cause ambiguity."""
    rule_runner_with_python_resolves.set_options(
        [
            "--source-root-patterns=['protos']",
            "--python-enable-resolves",
            "--python-resolves={'resolve-a': '', 'resolve-b': ''}",
        ]
    )
    rule_runner_with_python_resolves.write_files(
        {
            "protos/a/common.proto": "",
            "protos/a/BUILD": "protobuf_sources(python_resolve='resolve-a')",
            "protos/b/common.proto": "",  # Same name, different resolve
            "protos/b/BUILD": "protobuf_sources(python_resolve='resolve-b')",
        }
    )

    caplog.clear()
    result = rule_runner_with_python_resolves.request(ProtobufMapping, [])

    # Find resolve keys
    resolve_keys = {key.resolve: key for key in result.mapping.keys()}
    resolve_key_a = resolve_keys["resolve-a"]
    resolve_key_b = resolve_keys["resolve-b"]

    # Assert both resolves have their own mapping
    assert "a/common.proto" in result.mapping[resolve_key_a]
    assert "b/common.proto" in result.mapping[resolve_key_b]

    # Assert NO ambiguous_modules entries
    assert len(result.ambiguous_modules.get(resolve_key_a, {})) == 0
    assert len(result.ambiguous_modules.get(resolve_key_b, {})) == 0

    # No warnings should be logged
    assert "ambiguous" not in caplog.text.lower()


def test_default_resolve_behavior(rule_runner_with_python_resolves: RuleRunner) -> None:
    """Verify that targets without an explicit resolve get the default resolve."""
    rule_runner_with_python_resolves.set_options(
        [
            "--source-root-patterns=['protos']",
            "--python-enable-resolves",
            "--python-resolves={'python-default': '', 'other': ''}",
            "--python-default-resolve=python-default",
        ]
    )
    rule_runner_with_python_resolves.write_files(
        {
            "protos/a.proto": "import 'b.proto';",
            "protos/b.proto": "",
            "protos/BUILD": "protobuf_sources()",  # No explicit resolve
        }
    )

    result = rule_runner_with_python_resolves.request(ProtobufMapping, [])

    # Assert targets are in python-default resolve
    default_key = [key for key in result.mapping.keys() if key.resolve == "python-default"][0]
    assert "a.proto" in result.mapping[default_key]
    assert "b.proto" in result.mapping[default_key]

    # Test that dependency inference works
    def run_dep_inference(address: Address) -> InferredDependencies:
        tgt = rule_runner_with_python_resolves.get_target(address)
        return rule_runner_with_python_resolves.request(
            InferredDependencies,
            [InferProtobufDependencies(ProtobufDependencyInferenceFieldSet.create(tgt))],
        )

    deps = run_dep_inference(Address("protos", relative_file_path="a.proto"))
    assert deps == InferredDependencies([Address("protos", relative_file_path="b.proto")])


def test_empty_proto_file(rule_runner_with_python_resolves: RuleRunner) -> None:
    """Handle empty proto files in multi-resolve scenarios."""
    rule_runner_with_python_resolves.set_options(
        [
            "--source-root-patterns=['protos']",
            "--python-enable-resolves",
            "--python-resolves={'prod': ''}",
        ]
    )
    rule_runner_with_python_resolves.write_files(
        {
            "protos/empty.proto": "",
            "protos/BUILD": "protobuf_sources(python_resolve='prod')",
        }
    )

    result = rule_runner_with_python_resolves.request(ProtobufMapping, [])

    # Assert empty file is mapped correctly
    prod_key = [key for key in result.mapping.keys() if key.resolve == "prod"][0]
    assert "empty.proto" in result.mapping[prod_key]


def test_resolve_with_complex_import_paths(rule_runner_with_python_resolves: RuleRunner) -> None:
    """Test that complex import paths work correctly with multi-resolve."""
    rule_runner_with_python_resolves.set_options(
        [
            "--source-root-patterns=['protos']",
            "--python-enable-resolves",
            "--python-resolves={'prod': ''}",
        ]
    )
    rule_runner_with_python_resolves.write_files(
        {
            "protos/api/v1/service.proto": "import 'api/v1/models/user.proto';",
            "protos/api/v1/models/user.proto": "",
            "protos/api/v1/BUILD": "protobuf_sources(python_resolve='prod')",
            "protos/api/v1/models/BUILD": "protobuf_sources(python_resolve='prod')",
        }
    )

    def run_dep_inference(address: Address) -> InferredDependencies:
        tgt = rule_runner_with_python_resolves.get_target(address)
        return rule_runner_with_python_resolves.request(
            InferredDependencies,
            [InferProtobufDependencies(ProtobufDependencyInferenceFieldSet.create(tgt))],
        )

    deps = run_dep_inference(Address("protos/api/v1", relative_file_path="service.proto"))
    assert deps == InferredDependencies(
        [Address("protos/api/v1/models", relative_file_path="user.proto")]
    )
