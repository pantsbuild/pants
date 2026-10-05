# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.engine.addresses import Addresses
from pants.engine.internals.graph import resolve_targets
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    BoolField,
    Dependencies,
    InvalidFieldException,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    StringField,
    Target,
    TargetFilesGenerator,
    TargetFilesGeneratorSettings,
    TargetFilesGeneratorSettingsRequest,
    Targets,
    ValidatedDependencies,
    ValidateDependenciesRequest,
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
        Which tool generates code from this `.proto`.

        - `protoc` (default): Pants runs `protoc`. Output paths follow source roots and
          per-language options such as `python_source_root`.
        - `buf`: Pants runs `buf generate` with a `buf.gen.yaml` template, which decides
          the plugins and output paths. See the `buf_gen_template` field for how the
          template is found.

        Python supports both. TypeScript requires `buf`; Go, Java and Scala require
        `protoc`.
        """
    )


# A language's codegen rule skips targets whose generator it can't use, returning no files,
# because `export-codegen` asks every language to generate every Protobuf target. Code that
# depends on such a target fails dependency validation instead.


def uses_generator(target: Target, generator: str) -> bool:
    return target[ProtobufGeneratorField].value == generator


async def validate_protobuf_generator(
    request: ValidateDependenciesRequest, language: str, generator: str
) -> ValidatedDependencies:
    """Raise if `request`'s target depends on Protobuf that `language` can't generate."""
    dependencies = await resolve_targets(**implicitly({request.dependencies: Addresses}))
    for dep in dependencies:
        if dep.has_field(ProtobufGeneratorField) and not uses_generator(dep, generator):
            raise InvalidFieldException(
                f"{request.field_set.address} depends on {dep.address}, which has "
                f"`{ProtobufGeneratorField.alias}='{dep[ProtobufGeneratorField].value}'`, but "
                f"{language} can only be generated with {generator}. Set "
                f"`{ProtobufGeneratorField.alias}='{generator}'` on it."
            )
    return ValidatedDependencies()


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
