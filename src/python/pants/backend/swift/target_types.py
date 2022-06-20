# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    FieldSet,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
)

SWIFT_FILE_EXTENSIONS = (".swift",)


class SwiftSourceField(SingleSourceField):
    expected_file_extensions = SWIFT_FILE_EXTENSIONS


class SwiftGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = SWIFT_FILE_EXTENSIONS


@dataclass(frozen=True)
class SwiftFieldSet(FieldSet):
    required_fields = (SwiftSourceField,)

    source: SwiftSourceField


@dataclass(frozen=True)
class SwiftGeneratorFieldSet(FieldSet):
    required_fields = (SwiftGeneratorSourcesField,)

    sources: SwiftGeneratorSourcesField


# -----------------------------------------------------------------------------------------------
# `swift_source` and `swift_sources` targets
# -----------------------------------------------------------------------------------------------


class SwiftSourceTarget(Target):
    alias = "swift_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        SwiftSourceField,
    )
    help = "A single Swift source file."


class SwiftSourcesGeneratorSourcesField(SwiftGeneratorSourcesField):
    default = tuple(f"*{ext}" for ext in SWIFT_FILE_EXTENSIONS)


class SwiftSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "swift_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        SwiftSourcesGeneratorSourcesField,
    )
    generated_target_cls = SwiftSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (Dependencies,)
    help = "Generate a `swift_source` target for each file in the `sources` field."
