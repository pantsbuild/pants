# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    Sources,
    StringSequenceField,
    Target,
)

# -----------------------------------------------------------------------------------------------
# `cpp_binary` target
# -----------------------------------------------------------------------------------------------


class CppExternalLibraries(StringSequenceField):
    """Libraries that this target depends on that are not pants targets.

    For example, 'm' or 'rt' that are expected to be installed on the local system.
    """

    alias = "libraries"


class CppBinary(Target):
    """A C++ binary."""

    alias = "cpp_binary"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, Sources, CppExternalLibraries)
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `cpp_library` target
# -----------------------------------------------------------------------------------------------


class CppLibrary(Target):
    """A statically linked C++ library."""

    alias = "cpp_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, Sources)
    v1_only = True
