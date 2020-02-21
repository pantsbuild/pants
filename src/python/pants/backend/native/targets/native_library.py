# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta

from pants.backend.native.subsystems.native_build_step import ToolchainVariant
from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField, PrimitivesSetField
from pants.build_graph.target import Target


class NativeLibrary(Target, metaclass=ABCMeta):
    """A class wrapping targets containing sources for C-family languages and related code."""

    # TODO: replace this awkward classmethod with a mixin!
    @classmethod
    def produces_ctypes_native_library(cls, target):
        return isinstance(target, cls) and bool(target.ctypes_native_library)

    def __init__(
        self,
        address,
        payload=None,
        sources=None,
        ctypes_native_library=None,
        strict_deps=None,
        fatal_warnings=None,
        compiler_option_sets=None,
        toolchain_variant=None,
        **kwargs
    ):

        if not payload:
            payload = Payload()
        sources_field = self.create_sources_field(sources, address.spec_path, key_arg="sources")
        payload.add_fields(
            {
                "sources": sources_field,
                "ctypes_native_library": ctypes_native_library,
                "strict_deps": PrimitiveField(strict_deps),
                "fatal_warnings": PrimitiveField(fatal_warnings),
                "compiler_option_sets": PrimitivesSetField(compiler_option_sets),
                "toolchain_variant": PrimitiveField(toolchain_variant),
            }
        )

        if ctypes_native_library and not isinstance(ctypes_native_library, NativeArtifact):
            raise TargetDefinitionException(
                "Target must provide a valid pants '{}' object. Received an object with type '{}' "
                "and value: {}.".format(
                    NativeArtifact.alias(),
                    type(ctypes_native_library).__name__,
                    ctypes_native_library,
                )
            )

        super().__init__(address=address, payload=payload, **kwargs)

    @property
    def toolchain_variant(self):
        if not self.payload.toolchain_variant:
            return None

        return ToolchainVariant(self.payload.toolchain_variant)

    @property
    def strict_deps(self):
        return self.payload.strict_deps

    @property
    def fatal_warnings(self):
        return self.payload.fatal_warnings

    @property
    def compiler_option_sets(self):
        """For every element in this list, enable the corresponding flags on compilation of targets.

        :return: See constructor.
        :rtype: list
        """
        return self.payload.compiler_option_sets

    @property
    def ctypes_native_library(self):
        return self.payload.ctypes_native_library


class CLibrary(NativeLibrary):

    default_sources_globs = [
        "*.h",
        "*.c",
    ]

    @classmethod
    def alias(cls):
        return "ctypes_compatible_c_library"


class CppLibrary(NativeLibrary):

    default_sources_globs = [
        "*.h",
        "*.hpp",
        "*.cpp",
    ]

    @classmethod
    def alias(cls):
        return "ctypes_compatible_cpp_library"
