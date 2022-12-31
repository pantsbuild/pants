# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from pants.engine.rules import Rule, collect_rules
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
from pants.engine.unions import UnionRule

# Using the extensions referenced in C++ Core Guidelines FAQ
# https://isocpp.org/wiki/faq/coding-standards#hdr-file-ext
# https://isocpp.org/wiki/faq/coding-standards#src-file-ext
# NB: CMake uses these as the default C++ extensions: "C;M;c++;cc;cpp;cxx;mm;mpp;CPP;ixx;cppm"
CC_HEADER_FILE_EXTENSIONS = (
    ".h",
    ".hh",
    ".hpp",
)
C_SOURCE_FILE_EXTENSIONS = (".c",)
CXX_SOURCE_FILE_EXTENSIONS = (".cc", ".cpp", ".cxx")
CC_SOURCE_FILE_EXTENSIONS = C_SOURCE_FILE_EXTENSIONS + CXX_SOURCE_FILE_EXTENSIONS
CC_FILE_EXTENSIONS = CC_HEADER_FILE_EXTENSIONS + CC_SOURCE_FILE_EXTENSIONS


class CCLanguage(Enum):
    C = "c"
    CXX = "cxx"


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


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
