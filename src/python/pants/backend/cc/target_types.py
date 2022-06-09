# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.rules import collect_rules
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    FieldSet,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
    generate_multiple_sources_field_help_message,
)

CC_FILE_EXTENSIONS = (".c", ".h", ".cc", ".cpp", ".hpp")


class CCSourceField(SingleSourceField):
    expected_file_extensions = CC_FILE_EXTENSIONS


class CCGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = CC_FILE_EXTENSIONS


@dataclass(frozen=True)
class CCFieldSet(FieldSet):
    required_fields = (CCSourceField,)

    sources: CCSourceField


@dataclass(frozen=True)
class CCGeneratorFieldSet(FieldSet):
    required_fields = (CCGeneratorSourcesField,)

    sources: CCGeneratorSourcesField


# -----------------------------------------------------------------------------------------------
# `cc_source` and `cc_sources` targets
# -----------------------------------------------------------------------------------------------


class CCSourceTarget(Target):
    alias = "cc_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        CCSourceField,
    )
    help = "A single C/C++ source file or header file."


class CCSourcesGeneratorSourcesField(CCGeneratorSourcesField):
    default = tuple(f"*{ext}" for ext in CC_FILE_EXTENSIONS)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.cpp', 'new_*.cc', '!old_ignore.cc']`"
    )


class CCSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "cc_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CCSourcesGeneratorSourcesField,
    )
    generated_target_cls = CCSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (Dependencies,)
    help = "Generate a `cc_source` target for each file in the `sources` field."


def rules():
    return collect_rules()
