# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    Dependencies,
    MultipleSourcesField,
    OptionalSingleSourceField,
    SingleSourceField,
    StringField,
    Target,
    TargetFilesGenerator,
    Targets,
    generate_multiple_sources_field_help_message,
)
from pants.util.logging import LogLevel
from pants.util.strutil import help_text

OPENAPI_FILE_EXTENSIONS = (".json", ".yaml", ".yml")


class OpenApiField(SingleSourceField):
    expected_file_extensions = OPENAPI_FILE_EXTENSIONS


class OpenApiGeneratorField(MultipleSourcesField):
    expected_file_extensions = OPENAPI_FILE_EXTENSIONS


# -----------------------------------------------------------------------------------------------
# `openapi_document` and `openapi_documents` targets
# -----------------------------------------------------------------------------------------------


class OpenApiDocumentField(OpenApiField):
    pass


class OpenApiDocumentDependenciesField(Dependencies):
    pass


class OpenApiDocumentTarget(Target):
    alias = "openapi_document"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OpenApiDocumentDependenciesField,
        OpenApiDocumentField,
    )
    help = "A single OpenAPI document file."


class OpenApiDocumentGeneratorField(OpenApiGeneratorField):
    default = tuple(f"openapi{ext}" for ext in OPENAPI_FILE_EXTENSIONS)
    help = generate_multiple_sources_field_help_message("Example: `sources=['openapi.json']`")


class OpenApiDocumentGeneratorTarget(TargetFilesGenerator):
    alias = "openapi_documents"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OpenApiDocumentGeneratorField,
    )
    generated_target_cls = OpenApiDocumentTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (OpenApiDocumentDependenciesField,)
    help = (
        f"Generate an `{OpenApiDocumentTarget.alias}` target for each file in the `sources` field."
    )


class AllOpenApiDocumentTargets(Targets):
    pass


@rule(desc="Find all OpenAPI Document targets in project", level=LogLevel.DEBUG)
def find_all_openapi_document_targets(all_targets: AllTargets) -> AllOpenApiDocumentTargets:
    return AllOpenApiDocumentTargets(
        tgt for tgt in all_targets if tgt.has_field(OpenApiDocumentField)
    )


# -----------------------------------------------------------------------------------------------
# `openapi_source` and `openapi_sources` targets
# -----------------------------------------------------------------------------------------------


class OpenApiSourceField(OpenApiField):
    pass


class OpenApiSourceDependenciesField(Dependencies):
    pass


class OpenApiSourceTarget(Target):
    alias = "openapi_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OpenApiSourceDependenciesField,
        OpenApiSourceField,
    )
    help = "A single OpenAPI source file."


class OpenApiSourceGeneratorField(OpenApiGeneratorField):
    default = tuple(f"*{ext}" for ext in OPENAPI_FILE_EXTENSIONS)
    help = generate_multiple_sources_field_help_message("Example: `sources=['*.json']`")


class OpenApiSourceGeneratorTarget(TargetFilesGenerator):
    alias = "openapi_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OpenApiSourceGeneratorField,
    )
    generated_target_cls = OpenApiSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (OpenApiSourceDependenciesField,)
    help = f"Generate an `{OpenApiSourceTarget.alias}` target for each file in the `sources` field."


class AllOpenApiSourceTargets(Targets):
    pass


@rule(desc="Find all OpenAPI source targets in project", level=LogLevel.DEBUG)
def find_all_openapi_source_targets(all_targets: AllTargets) -> AllOpenApiSourceTargets:
    return AllOpenApiSourceTargets(tgt for tgt in all_targets if tgt.has_field(OpenApiSourceField))


# -----------------------------------------------------------------------------------------------
# `openapi_bundle` target
# -----------------------------------------------------------------------------------------------


class OpenApiBundleSourceRootField(StringField):
    alias = "bundle_source_root"
    help = help_text(
        f"""
        The source root to bundle OpenAPI documents under.

        If unspecified, the source root the `{OpenApiDocumentGeneratorTarget.alias}` is under will be used.
        """
    )


class OpenApiBundleDependenciesField(Dependencies):
    pass


class OpenApiBundleDummySourceField(OptionalSingleSourceField):
    alias = "_source"


class OpenApiBundleTarget(Target):
    alias = "openapi_bundle"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OpenApiBundleDummySourceField,
        OpenApiBundleDependenciesField,
        OpenApiBundleSourceRootField,
    )
    help = help_text("An OpenAPI document bundled as a single source.")


def rules():
    return collect_rules()
