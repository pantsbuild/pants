# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    BoolField,
    Dependencies,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    StringField,
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


class ProtobufGeneratorField(StringField):
    alias = "protobuf_generator"
    valid_choices = ("protoc", "buf")
    default = "protoc"
    help = help_text(
        """
        Which tool to use to generate code from this `.proto`. Applies to every
        language backend that consumes the target.

        - `protoc` (default): use the `protoc` compiler. Output paths follow Pants's
          source-root conventions and any per-language overrides
          (e.g. `python_source_root`).
        - `buf`: use `buf generate` with a `buf.gen.yaml` template. Plugins, output
          paths, and managed-mode rewrites come from the template, not from Pants.
          The template is resolved per-target via `buf_gen_template`, falling back
          to `[buf].gen_template`, falling back to discovery of `buf.gen.yaml` at
          the repository root.

        A single `buf.gen.yaml` typically declares plugins for several languages, so
        this is a target-level choice rather than a per-language one. To get
        protoc-style behavior for an individual language inside a buf-driven build,
        declare a `protoc_builtin:` plugin entry in `buf.gen.yaml`.
        """
    )


class AllProtobufTargets(Targets):
    pass


@rule(desc="Find all Protobuf targets in project", level=LogLevel.DEBUG)
async def find_all_protobuf_targets(targets: AllTargets) -> AllProtobufTargets:
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
        ProtobufGeneratorField,
    )
    help = help_text(
        f"""
        A single Protobuf file used to generate various languages.

        See language-specific docs:
            Python: {doc_url("docs/python/integrations/protobuf-and-grpc")}
            Go: {doc_url("docs/go/integrations/protobuf")}
        """
    )


# -----------------------------------------------------------------------------------------------
# `protobuf_sources` target generator
# -----------------------------------------------------------------------------------------------


class GeneratorSettingsRequest(TargetFilesGeneratorSettingsRequest):
    pass


@rule
async def generator_settings(
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
        ProtobufGeneratorField,
        ProtobufDependenciesField,
    )
    settings_request_cls = GeneratorSettingsRequest
    help = "Generate a `protobuf_source` target for each file in the `sources` field."


def rules():
    return [
        *collect_rules(),
        UnionRule(TargetFilesGeneratorSettingsRequest, GeneratorSettingsRequest),
    ]
