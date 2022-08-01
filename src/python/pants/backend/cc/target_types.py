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
    StringSequenceField,
    Target,
    TargetFilesGenerator,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import softwrap

# Using the extensions referenced in C++ Core Guidelines FAQ
# https://isocpp.org/wiki/faq/coding-standards#hdr-file-ext
# https://isocpp.org/wiki/faq/coding-standards#src-file-ext
CC_HEADER_FILE_EXTENSIONS = (
    ".h",
    ".hh",
    ".hpp",
)
CC_SOURCE_FILE_EXTENSIONS = (
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
)
CC_FILE_EXTENSIONS = CC_HEADER_FILE_EXTENSIONS + CC_SOURCE_FILE_EXTENSIONS


class CCDependenciesField(Dependencies):
    pass


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
        CCDependenciesField,
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


# -----------------------------------------------------------------------------------------------
# `cc_library` and `cc_binary` targets
# -----------------------------------------------------------------------------------------------


class CCCompileOptionsField(StringSequenceField):
    alias = "compile_options"
    help = softwrap(
        """
        TODO
        """
    )


class CCDefinesField(StringSequenceField):
    alias = "defines"
    help = softwrap(
        """
        TODO
        """
    )


class CCHeadersField(StringSequenceField):
    alias = "headers"
    help = softwrap(
        """
        TODO
        Public headers which are exported by this target, and can be imported by others.
        """
    )


class CCBinaryFieldSet(FieldSet):
    required_fields = (CCDependenciesField,)

    dependencies: CCDependenciesField


class CCLibraryTarget(Target):
    alias = "cc_library"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CCCompileOptionsField,
        CCDefinesField,
        CCDependenciesField,
        CCHeadersField,
    )
    help = softwrap(
        """
        TODO
        """
    )


class CCBinaryTarget(Target):
    alias = "cc_binary"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CCCompileOptionsField,
        CCDefinesField,
        CCDependenciesField,
    )
    help = softwrap(
        """
        TODO
        """
    )


def rules():
    return collect_rules()
