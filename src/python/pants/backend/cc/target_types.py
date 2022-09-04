# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath

from pants.core.goals.package import OutputPathField
from pants.engine.rules import collect_rules
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    BoolField,
    Dependencies,
    FieldSet,
    MultipleSourcesField,
    SingleSourceField,
    StringField,
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
C_SOURCE_FILE_EXTENSIONS = (".c",)
CPP_SOURCE_FILE_EXTENSIONS = (".cc", ".cpp", ".cxx")
CC_SOURCE_FILE_EXTENSIONS = C_SOURCE_FILE_EXTENSIONS + CPP_SOURCE_FILE_EXTENSIONS
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
    compile_flags: CCCompileFlagsField
    defines: CCDefinesField
    language: CCLanguageField


@dataclass(frozen=True)
class CCGeneratorFieldSet(FieldSet):
    required_fields = (CCGeneratorSourcesField,)

    sources: CCGeneratorSourcesField


# -----------------------------------------------------------------------------------------------
# `cc_source` and `cc_sources` targets
# -----------------------------------------------------------------------------------------------


class CCCompileFlagsField(StringSequenceField):
    alias = "compile_flags"
    help = softwrap(
        """
        Flags passed to the compiler.
        These flags are merged with the toolchain-level defines, with the target-level flags taking precedence.
        """
    )


class CCDefinesField(StringSequenceField):
    alias = "defines"
    help = softwrap(
        """
        A list of strings to define in the preprocessor. Will be prefixed by -D at the command line.
        These defines are merged with the toolchain-level defines, with the target-level definitions taking precedence.
        """
    )


class CCLanguage(Enum):
    C = "c"
    CPP = "c++"


class CCLanguageField(StringField, AsyncFieldMixin):
    alias = "language"
    default = None
    valid_choices = CCLanguage
    help = softwrap(
        """
        A field to indicate what programming language the source is written in.

        The default selection is `None`, in which case we attempt to determine the correct compiler based on file extension.
        Alternatively, `c` or `c++` may be specified to force compilation with the specified toolchains/flags.
        """
    )

    def normalized_value(self) -> CCLanguage:
        """Get the value after applying the default and validating that the key is recognized."""
        if self.value is None:
            filename = self.address.filename
            return (
                CCLanguage.CPP
                if PurePath(filename).suffix in CPP_SOURCE_FILE_EXTENSIONS
                else CCLanguage.C
            )
        return CCLanguage(self.value)


class CCSourceTarget(Target):
    alias = "cc_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CCCompileFlagsField,
        CCDefinesField,
        CCDependenciesField,
        CCLanguageField,
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
    moved_fields = (
        CCCompileFlagsField,
        CCDefinesField,
        CCDependenciesField,
        CCLanguageField,
    )
    help = "Generate a `cc_source` target for each file in the `sources` field."


# -----------------------------------------------------------------------------------------------
# `cc_library` and `cc_binary` targets
# -----------------------------------------------------------------------------------------------


class CCLinkTypeField(StringField):
    alias = "link_type"
    default = "shared"
    valid_choices = ("shared", "static")
    help = softwrap(
        """
        This field determines the link basis for `cc_library` targets.
        """
    )


class CCLinkFlagsField(StringSequenceField):
    alias = "link_flags"
    help = softwrap(
        """
        TODO
        """
    )


class CCHeadersField(Dependencies):
    alias = "headers"
    help = softwrap(
        """
        This field specifies public headers which are made available to dependent targets.
        The headers should be specified as `cc_source` or `cc_sources` targets.
        """
    )


class CCLibraryTarget(Target):
    alias = "cc_library"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CCDependenciesField,
        CCHeadersField,
        # CCLinkFlagsField, # TODO
        CCLinkTypeField,
        OutputPathField,
    )
    help = softwrap(
        """
        A static or shared cc library (depending on `link_type`).
        """
    )


# TODO: Need this so building a binary doesn't build a library too
class CCContrivedField(BoolField):
    alias = "contrived"
    default = False
    help = softwrap(
        """
        Contrived Placeholder.
        """
    )


class CCBinaryTarget(Target):
    alias = "cc_binary"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CCContrivedField,
        CCDependenciesField,
        # CCLinkFlagsField, # TODO
        OutputPathField,
    )
    help = softwrap(
        """
        A cc binary.
        """
    )


def rules():
    return collect_rules()
