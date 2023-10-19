# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Type

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.engine.internals.native_engine import Field
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    BoolField,
    Dependencies,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
    TargetFilesGeneratorSettings,
    TargetFilesGeneratorSettingsRequest,
    Targets,
    generate_file_based_overrides_field_help_message,
    generate_multiple_sources_field_help_message,
)
from pants.engine.unions import UnionRule
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.strutil import help_text


class ProtobufDependenciesField(Dependencies):
    pass


class ProtobufGrpcToggleField(BoolField):
    alias = "grpc"
    default = False
    help = "Whether to generate gRPC code or not."


class AllProtobufTargets(Targets):
    pass


@rule(desc="Find all Protobuf targets in project", level=LogLevel.DEBUG)
def find_all_protobuf_targets(targets: AllTargets) -> AllProtobufTargets:
    return AllProtobufTargets(tgt for tgt in targets if tgt.has_field(ProtobufSourceField))


# -----------------------------------------------------------------------------------------------
# `protobuf_source` target
# -----------------------------------------------------------------------------------------------


class ProtobufSourceField(SingleSourceField):
    expected_file_extensions = (".proto",)


class ProtobufSourceTarget(Target):
    alias = "protobuf_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ProtobufDependenciesField,
        ProtobufSourceField,
        ProtobufGrpcToggleField,
    )
    help = help_text(
        f"""
        A single Protobuf file used to generate various languages.

        See language-specific docs:
            Python: {doc_url('protobuf-python')}
            Go: {doc_url('protobuf-go')}
        """
    )


# -----------------------------------------------------------------------------------------------
# `protobuf_sources` target generator
# -----------------------------------------------------------------------------------------------


class GeneratorSettingsRequest(TargetFilesGeneratorSettingsRequest):
    pass


@rule
def generator_settings(
    _: GeneratorSettingsRequest,
    protoc: Protoc,
) -> TargetFilesGeneratorSettings:
    return TargetFilesGeneratorSettings(
        add_dependencies_on_all_siblings=not protoc.dependency_inference
    )


class ProtobufSourcesGeneratingSourcesField(MultipleSourcesField):
    default = ("*.proto",)
    expected_file_extensions = (".proto",)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.proto', 'new_*.proto', '!old_ignore*.proto']`"
    )


class ProtobufSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        ProtobufSourceTarget.alias,
        """
        overrides={
            "foo.proto": {"grpc": True},
            "bar.proto": {"description": "our user model"},
            ("foo.proto", "bar.proto"): {"tags": ["overridden"]},
        }
        """,
    )


class ProtobufSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "protobuf_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ProtobufSourcesGeneratingSourcesField,
        ProtobufSourcesOverridesField,
    )
    generated_target_cls = ProtobufSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        ProtobufGrpcToggleField,
        ProtobufDependenciesField,
    )
    settings_request_cls = GeneratorSettingsRequest
    help = "Generate a `protobuf_source` target for each file in the `sources` field."

    @classmethod
    def register_plugin_field(cls, field: Type[Field], move: bool = False) -> UnionRule:
        rules = super().register_plugin_field(field)
        if move and field not in cls.moved_fields:
            cls.moved_fields = (*cls.moved_fields, field)
        return rules


def rules():
    return [
        *collect_rules(),
        UnionRule(TargetFilesGeneratorSettingsRequest, GeneratorSettingsRequest),
    ]
