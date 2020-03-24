# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import abstractmethod
from enum import Enum

from pants.build_graph.mirrored_target_option_mixin import MirroredTargetOptionMixin
from pants.engine.platform import Platform
from pants.option.compiler_option_sets_mixin import CompilerOptionSetsMixin
from pants.subsystem.subsystem import Subsystem
from pants.util.enums import match
from pants.util.memo import memoized_property
from pants.util.meta import classproperty


class ToolchainVariant(Enum):
    gnu = "gnu"
    llvm = "llvm"


class NativeBuildStep(CompilerOptionSetsMixin, MirroredTargetOptionMixin, Subsystem):
    """Settings which are specific to a target and do not need to be the same for compile and
    link."""

    options_scope = "native-build-step"

    mirrored_target_option_actions = {
        "compiler_option_sets": lambda tgt: tgt.compiler_option_sets,
        "toolchain_variant": lambda tgt: tgt.toolchain_variant,
    }

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--compiler-option-sets",
            advanced=True,
            default=(),
            type=list,
            fingerprint=True,
            help='The default for the "compiler_option_sets" argument '
            "for targets of this language.",
        )

        register(
            "--toolchain-variant",
            advanced=True,
            default=match(
                Platform.current,
                {Platform.darwin: ToolchainVariant.llvm, Platform.linux: ToolchainVariant.gnu},
            ),
            type=ToolchainVariant,
            fingerprint=True,
            help="Whether to use gcc (gnu) or clang (llvm) to compile C and C++. Note that "
            "currently, despite the choice of toolchain, all linking is done with binutils "
            "ld on Linux, and the XCode CLI Tools on MacOS.",
        )

    def get_compiler_option_sets_for_target(self, target):
        return self.get_scalar_mirrored_target_option("compiler_option_sets", target)

    def get_toolchain_variant_for_target(self, target):
        return self.get_scalar_mirrored_target_option("toolchain_variant", target)

    @classproperty
    def get_compiler_option_sets_enabled_default_value(cls):
        return {"fatal_warnings": ["-Werror"]}


class CompileSettingsBase(Subsystem):
    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (NativeBuildStep.scoped(cls),)

    @classproperty
    @abstractmethod
    def header_file_extensions_default(cls):
        """Default value for --header-file-extensions."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--header-file-extensions",
            advanced=True,
            default=cls.header_file_extensions_default,
            type=list,
            fingerprint=True,
            help="The file extensions which should not be provided to the compiler command line.",
        )

    @memoized_property
    def native_build_step(self):
        return NativeBuildStep.scoped_instance(self)

    @memoized_property
    def header_file_extensions(self):
        return self.get_options().header_file_extensions


class CCompileSettings(CompileSettingsBase):
    options_scope = "c-compile-settings"

    header_file_extensions_default = [".h"]


class CppCompileSettings(CompileSettingsBase):
    options_scope = "cpp-compile-settings"

    header_file_extensions_default = [".h", ".hpp", ".hxx", ".tpp"]


# TODO: add a fatal_warnings kwarg to NativeArtifact and make a LinkSharedLibrariesSettings subclass
# of NativeBuildStep here! The method should work even though NativeArtifact is not a
# Target.
