# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict, Iterable, Optional, Tuple, Union

from pants.backend.native.subsystems.native_build_step import ToolchainVariant
from pants.backend.native.targets.external_native_library import ConanRequirement
from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.build_graph.address import Address
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    InvalidFieldException,
    InvalidFieldTypeException,
    PrimitiveField,
    Sources,
    StringField,
    StringSequenceField,
    Target,
)
from pants.util.collections import ensure_list, ensure_str_list
from pants.util.frozendict import FrozenDict

# -----------------------------------------------------------------------------------------------
# `ctypes_compatible_c_library` and `ctypes_compatible_cpp_library` targets
# -----------------------------------------------------------------------------------------------


class CSources(Sources):
    default = ("*.h", "*.c")


class CppSources(Sources):
    # TODO: Add support for all the different C++ file extensions, including `.cc` and `.cxx`. See
    #  https://stackoverflow.com/a/1546107.
    default = ("*.h", "*.hpp", "*.cpp")


class CtypesNativeLibrary(PrimitiveField):
    alias = "ctypes_native_library"
    value: NativeArtifact
    required = True

    @classmethod
    def compute_value(
        cls, raw_value: Optional[NativeArtifact], *, address: Address
    ) -> NativeArtifact:
        value = super().compute_value(raw_value, address=address)
        if not isinstance(value, NativeArtifact):
            raise InvalidFieldTypeException(
                address, cls.alias, value, expected_type="a `native_artifact` object"
            )
        return value


class NativeFatalWarnings(BoolField):
    alias = "fatal_warnings"
    default = False


# NB: This is very similar to the JvmStrictDeps field in `backend/jvm`. Consider using the same
# field for both purposes.
class NativeStrictDeps(BoolField):
    """Whether to include only dependencies directly declared in the BUILD file.

    If this is False, all transitive dependencies are used when compiling and linking native code.
    """

    alias = "strict_deps"
    default = False


class ToolchainVariantField(StringField):
    """Whether to use gcc (gnu) or clang (llvm) to compile.

    Note that currently, despite the choice of toolchain, all linking is done with binutils ld on
    Linux, and the XCode CLI Tools on MacOS.
    """

    alias = "toolchain_variant"

    @classmethod
    def compute_value(cls, raw_value: Optional[str], *, address: Address) -> Optional[str]:
        value = super().compute_value(raw_value, address=address)
        valid_options = list(ToolchainVariant.__members__.keys())
        if value not in valid_options:
            raise InvalidFieldException(
                f"The {repr(cls.alias)} field in target {address} must be one of {valid_options}, "
                f"but was {repr(raw_value)}."
            )
        return value


class NativeCompilerOptionSets(StringSequenceField):
    alias = "compiler_options_sets"


NATIVE_LIBRARY_COMMON_FIELDS = (
    *COMMON_TARGET_FIELDS,
    Dependencies,
    CtypesNativeLibrary,
    NativeStrictDeps,
    NativeFatalWarnings,
    ToolchainVariantField,
    NativeCompilerOptionSets,
)


class CLibrary(Target):
    """A C library that is compatible with Python's ctypes."""

    alias = "ctypes_compatible_c_library"
    core_fields = (*NATIVE_LIBRARY_COMMON_FIELDS, CSources)


class CppLibrary(Target):
    """A C++ library that is compatible with Python's ctypes."""

    alias = "ctypes_compatible_cpp_library"
    core_fields = (*NATIVE_LIBRARY_COMMON_FIELDS, CppSources)


# -----------------------------------------------------------------------------------------------
# `external_native_library` target
# -----------------------------------------------------------------------------------------------


class ConanPackages(PrimitiveField):
    """The `ConanRequirement`s to resolve into a `packaged_native_library()` target."""

    alias = "packages"
    value: Optional[Tuple[ConanRequirement, ...]]
    required = True

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[ConanRequirement]], *, address: Address
    ) -> Optional[Tuple[ConanRequirement, ...]]:
        value_or_default = super().compute_value(raw_value, address=address)
        if value_or_default is None:
            return None
        try:
            ensure_list(value_or_default, expected_type=ConanRequirement)
        except ValueError:
            raise InvalidFieldTypeException(
                address,
                cls.alias,
                value_or_default,
                expected_type="an iterable of `conan_requirement` objects (e.g. a list)",
            )
        return tuple(sorted(value_or_default))


class ConanNativeLibrary(Target):
    """A set of Conan package strings to be passed to the Conan package manager."""

    alias = "external_native_library"
    core_fields = (*COMMON_TARGET_FIELDS, ConanPackages)


# -----------------------------------------------------------------------------------------------
# `packaged_native_library` target
# -----------------------------------------------------------------------------------------------


class NativeIncludeRelpath(StringField):
    """The path where C/C++ headers are located, relative to this target's directory.

    Libraries depending on this target will be able to #include files relative to this directory.
    """

    alias = "include_relpath"


class NativeLibRelpath(StringField):
    """The path where native libraries are located, relative to this target's directory."""

    alias = "lib_relpath"


class NativeLibNames(PrimitiveField):
    """Libraries to add to the linker command line.

    These libraries become `-l<name>` arguments, so they must exist and be named
    `lib<name>.so` (or `lib<name>.dylib` depending on the platform) or the linker will exit with
    an error.

    This field may also be a dict mapping the OS name ('darwin' or 'linux') to a list of
    such strings.
    """

    alias = "native_lib_names"
    value: Optional[Union[Tuple[str, ...], FrozenDict[str, Tuple[str, ...]]]]
    default = None

    @classmethod
    def compute_value(
        cls,
        raw_value: Optional[Union[Iterable[str], Dict[str, Iterable[str]]]],
        *,
        address: Address,
    ) -> Optional[Union[Tuple[str, ...], FrozenDict[str, Tuple[str, ...]]]]:
        value_or_default = super().compute_value(raw_value, address=address)
        invalid_field_type_exception = InvalidFieldTypeException(
            address,
            cls.alias,
            value_or_default,
            expected_type=(
                "either an iterable of strings or a dictionary of platforms to iterable of "
                "strings"
            ),
        )
        if isinstance(value_or_default, dict):
            try:
                return FrozenDict(
                    {
                        platform: tuple(sorted(ensure_str_list(lib_names)))
                        for platform, lib_names in value_or_default.items()
                    }
                )
            except ValueError:
                raise invalid_field_type_exception
        try:
            ensure_str_list(value_or_default)
        except ValueError:
            raise invalid_field_type_exception
        return tuple(sorted(value_or_default))


class PackagedNativeLibrary(Target):
    """A container for headers and libraries from external sources.

    This target type is intended to be generated by a codegen task to wrap various sources of C/C++
    packages in a homogeneous container. It can also be used to wrap native libraries which are
    checked into the repository -- the `sources` argument does not allow files outside of the
    buildroot.
    """

    alias = "packaged_native_library"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        Sources,
        NativeIncludeRelpath,
        NativeLibRelpath,
        NativeLibNames,
    )
