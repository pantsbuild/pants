# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
)

OPENAPI_FILE_EXTENSIONS = (".json", ".yaml")


class OpenApiField(SingleSourceField):
    expected_file_extensions = OPENAPI_FILE_EXTENSIONS


class OpenApiGeneratorField(MultipleSourcesField):
    expected_file_extensions = OPENAPI_FILE_EXTENSIONS


# -----------------------------------------------------------------------------------------------
# `openapi_definition` and `openapi_definitions` targets
# -----------------------------------------------------------------------------------------------


class OpenApiDefinitionField(OpenApiField):
    pass


class OpenApiDefinitionDependenciesField(Dependencies):
    pass


class OpenApiDefinitionTarget(Target):
    alias = "openapi_definition"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OpenApiDefinitionDependenciesField,
        OpenApiDefinitionField,
    )
    help = "A single OpenAPI definition file."


class OpenApiDefinitionGeneratorField(OpenApiGeneratorField):
    default = tuple(f"openapi{ext}" for ext in OPENAPI_FILE_EXTENSIONS)


class OpenApiDefinitionGeneratorTarget(TargetFilesGenerator):
    alias = "openapi_definitions"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OpenApiDefinitionGeneratorField,
    )
    generated_target_cls = OpenApiDefinitionTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (OpenApiDefinitionDependenciesField,)
    help = "Generate an `openapi_definition` target for each file in the `sources` field."


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


class OpenApiSourceGeneratorTarget(TargetFilesGenerator):
    alias = "openapi_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OpenApiSourceGeneratorField,
    )
    generated_target_cls = OpenApiSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (OpenApiSourceDependenciesField,)
    help = "Generate an `openapi_source` target for each file in the `sources` field."
