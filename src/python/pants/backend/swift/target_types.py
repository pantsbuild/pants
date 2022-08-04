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
    generate_multiple_sources_field_help_message,
)

SWIFT_FILE_EXTENSIONS = (".swift",)


class SwiftDependenciesField(Dependencies):
    pass


class SwiftSourceField(SingleSourceField):
    expected_file_extensions = SWIFT_FILE_EXTENSIONS


class SwiftGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = SWIFT_FILE_EXTENSIONS


# -----------------------------------------------------------------------------------------------
# `swift_source` and `swift_sources` targets
# -----------------------------------------------------------------------------------------------


class SwiftSourceTarget(Target):
    alias = "swift_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        SwiftDependenciesField,
        SwiftSourceField,
    )
    help = "A single Swift source file."


class SwiftSourcesGeneratorSourcesField(SwiftGeneratorSourcesField):
    default = tuple(f"*{ext}" for ext in SWIFT_FILE_EXTENSIONS)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['utils.swift', 'subdir/*.swift', '!ignore_me.swift']`"
    )


class SwiftSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "swift_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        SwiftSourcesGeneratorSourcesField,
    )
    generated_target_cls = SwiftSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (SwiftDependenciesField,)
    help = "Generate a `swift_source` target for each file in the `sources` field."
