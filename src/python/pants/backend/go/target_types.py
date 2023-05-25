# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Iterable, Optional, Sequence, Tuple

from pants.core.goals.package import OutputPathField
from pants.core.goals.run import RestartableField
from pants.core.goals.test import TestExtraEnvVarsField, TestTimeoutField
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.addresses import Address
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    BoolField,
    Dependencies,
    InvalidFieldException,
    InvalidTargetException,
    MultipleSourcesField,
    StringField,
    StringSequenceField,
    Target,
    TargetGenerator,
    TriBoolField,
    ValidNumbers,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import help_text

# -----------------------------------------------------------------------------------------------
# Build option fields
# -----------------------------------------------------------------------------------------------


class GoCgoEnabledField(TriBoolField):
    """Enables Cgo support."""

    alias = "cgo_enabled"
    help = help_text(
        """
        Enable Cgo support, which allows Go and C code to interact. This option must be enabled for any
        packages making use of Cgo to actually be compiled with Cgo support.

        This field can be specified on several different target types, including `go_binary` and `go_mod` target
        types. If this field is specified on a `go_binary` target, then that instance takes precedence over other
        configuration when building the applicable executable. The applicable `go_mod` target will be checked next
        as a fallback. Finally, if neither target specifies this field, then the value will be taken from
        the value of the `[golang].cgo_enabled` option. (Note: That option will be deprecated in a future Pants
        version.)

        See https://go.dev/blog/cgo and https://pkg.go.dev/cmd/cgo for additional information about Cgo.
        """
    )


class GoRaceDetectorEnabledField(TriBoolField):
    """Enables the Go data race detector."""

    alias = "race"
    help = help_text(
        """
        Enable compiling the binary with the Go data race detector.

        See https://go.dev/doc/articles/race_detector for additional information about the Go data race detector.
        """
    )


class GoTestRaceDetectorEnabledField(GoRaceDetectorEnabledField):
    alias = "test_race"
    help = help_text(
        """
        Enable compiling this package's test binary with the Go data race detector.

        See https://go.dev/doc/articles/race_detector for additional information about the Go data race detector.
        """
    )


class GoMemorySanitizerEnabledField(TriBoolField):
    """Enables the C/C++ memory sanitizer."""

    alias = "msan"
    help = help_text(
        """
        Enable interoperation between Go code and the C/C++ "memory sanitizer."

        See https://github.com/google/sanitizers/wiki/MemorySanitizer for additional information about
        the C/C++ memory sanitizer.
        """
    )


class GoTestMemorySanitizerEnabledField(GoRaceDetectorEnabledField):
    alias = "test_msan"
    help = help_text(
        """
        Enable interoperation between Go code and the C/C++ "memory sanitizer" when building this package's
        test binary.

        See https://github.com/google/sanitizers/wiki/MemorySanitizer for additional information about
        the C/C++ memory sanitizer.
        """
    )


class GoAddressSanitizerEnabledField(TriBoolField):
    """Enables the C/C++ address sanitizer."""

    alias = "asan"
    help = help_text(
        """
        Enable interoperation between Go code and the C/C++ "address sanitizer."

        See https://github.com/google/sanitizers/wiki/AddressSanitizer for additional information about
        the C/C++ address sanitizer.
        """
    )


class GoTestAddressSanitizerEnabledField(GoRaceDetectorEnabledField):
    alias = "test_asan"
    help = help_text(
        """
        Enable interoperation between Go code and the C/C++ "address sanitizer" when building this package's
        test binary.

        See https://github.com/google/sanitizers/wiki/AddressSanitizer for additional information about
        the C/C++ address sanitizer.
        """
    )


class GoAssemblerFlagsField(StringSequenceField):
    alias = "assembler_flags"
    help = help_text(
        """
        Extra flags to pass to the Go assembler (i.e., `go tool asm`) when assembling Go-format assembly code.

        Note: These flags will not be added to gcc/clang-format assembly that is assembled in packages using Cgo.

        This field can be specified on several different target types:

        - On `go_mod` targets, the assembler flags are used when building any package involving the module
        including both first-party (i.e., `go_package` targets) and third-party dependencies.

        - On `go_binary` targets, the assembler flags are used when building any packages comprising that binary
        including third-party dependencies. These assembler flags will be added after any assembler flags
        added by any `assembler_flags` field set on the applicable `go_mod` target.

        - On `go_package` targets, the assembler flags are used only for building that specific package and not
        for any other package. These assembler flags will be added after any assembler flags added by any
        `assembler_flags` field set on the applicable `go_mod` target or applicable `go_binary` target.

        Run `go doc cmd/asm` to see the flags supported by `go tool asm`.
        """
    )


class GoCompilerFlagsField(StringSequenceField):
    alias = "compiler_flags"
    help = help_text(
        """
        Extra flags to pass to the Go compiler (i.e., `go tool compile`) when compiling Go code.

        This field can be specified on several different target types:

        - On `go_mod` targets, the compiler flags are used when compiling any package involving the module
        including both first-party (i.e., `go_package` targets) and third-party dependencies.

        - On `go_binary` targets, the compiler flags are used when compiling any packages comprising that binary
        including third-party dependencies. These compiler flags will be added after any compiler flags
        added by any `compiler_flags` field set on the applicable `go_mod` target.

        - On `go_package` targets, the compiler flags are used only for compiling that specific package and not
        for any other package. These compiler flags will be added after any compiler flags added by any
        `compiler_flags` field set on the applicable `go_mod` target or applicable `go_binary` target.

        Run `go doc cmd/compile` to see the flags supported by `go tool compile`.
        """
    )


class GoLinkerFlagsField(StringSequenceField):
    alias = "linker_flags"
    help = help_text(
        """
        Extra flags to pass to the Go linker (i.e., `go tool link`) when linking Go binaries.

        This field can be specified on several different target types:

        - On `go_mod` targets, the linker flags are used when linking any binary involving the module
        including both `go_binary` targets and test binaries for `go_package` targets within the module.

        - On `go_binary` targets, the linker flags are used when linking that binary. These linker flags
        will be added after any linker flags added by any `linker_flags` field set on the applicable
        `go_mod` target.

        Run `go doc cmd/link` to see the flags supported by `go tool link`.
        """
    )


# -----------------------------------------------------------------------------------------------
# `go_third_party_package` target
# -----------------------------------------------------------------------------------------------


class GoImportPathField(StringField):
    alias = "import_path"
    help = help_text(
        """
        Import path in Go code to import this package.

        This field should not be overridden; use the value from target generation.
        """
    )
    required = True
    value: str


class GoThirdPartyPackageDependenciesField(Dependencies):
    pass


class GoThirdPartyPackageTarget(Target):
    alias = "go_third_party_package"
    core_fields = (*COMMON_TARGET_FIELDS, GoThirdPartyPackageDependenciesField, GoImportPathField)
    help = help_text(
        """
        A package from a third-party Go module.

        You should not explicitly create this target in BUILD files. Instead, add a `go_mod`
        target where you have your `go.mod` file, which will generate
        `go_third_party_package` targets for you.

        Make sure that your `go.mod` and `go.sum` files include this package's module.
        """
    )

    def validate(self) -> None:
        if not self.address.is_generated_target:
            raise InvalidTargetException(
                f"The `{self.alias}` target type should not be manually created in BUILD "
                f"files, but it was created for {self.address}.\n\n"
                "Instead, add a `go_mod` target where you have your `go.mod` file, which will "
                f"generate `{self.alias}` targets for you based on the `require` directives in "
                f"your `go.mod`."
            )


# -----------------------------------------------------------------------------------------------
# `go_mod` target generator
# -----------------------------------------------------------------------------------------------


class GoModSourcesField(MultipleSourcesField):
    alias = "_sources"
    default = ("go.mod", "go.sum")
    expected_num_files = range(1, 3)  # i.e. 1 or 2.

    @property
    def go_mod_path(self) -> str:
        return os.path.join(self.address.spec_path, "go.mod")

    @property
    def go_sum_path(self) -> str:
        return os.path.join(self.address.spec_path, "go.sum")

    def validate_resolved_files(self, files: Sequence[str]) -> None:
        super().validate_resolved_files(files)
        if self.go_mod_path not in files:
            raise InvalidFieldException(
                f"The {repr(self.alias)} field in target {self.address} must include "
                f"{self.go_mod_path}, but only had: {list(files)}\n\n"
                f"Make sure that you're declaring the `{GoModTarget.alias}` target in the same "
                "directory as your `go.mod` file."
            )
        invalid_files = set(files) - {self.go_mod_path, self.go_sum_path}
        if invalid_files:
            raise InvalidFieldException(
                f"The {repr(self.alias)} field in target {self.address} must only include "
                f"`{self.go_mod_path}` and optionally {self.go_sum_path}, but had: "
                f"{sorted(invalid_files)}\n\n"
                f"Make sure that you're declaring the `{GoModTarget.alias}` target in the same "
                f"directory as your `go.mod` file and that you don't override the `{self.alias}` "
                "field."
            )


# TODO: This field probably shouldn't be registered.
class GoModDependenciesField(Dependencies):
    alias = "_dependencies"


class GoModTarget(TargetGenerator):
    alias = "go_mod"
    help = help_text(
        """
        A first-party Go module (corresponding to a `go.mod` file).

        Generates `go_third_party_package` targets based on the `require` directives in your
        `go.mod`.

        If you have third-party packages, make sure you have an up-to-date `go.sum`. Run
        `go mod tidy` directly to update your `go.mod` and `go.sum`.
        """
    )
    generated_target_cls = GoThirdPartyPackageTarget
    core_fields = (
        *COMMON_TARGET_FIELDS,
        GoModDependenciesField,
        GoModSourcesField,
        GoCgoEnabledField,
        GoRaceDetectorEnabledField,
        GoMemorySanitizerEnabledField,
        GoAddressSanitizerEnabledField,
        GoAssemblerFlagsField,
        GoCompilerFlagsField,
        GoLinkerFlagsField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = ()


# -----------------------------------------------------------------------------------------------
# `go_package` target
# -----------------------------------------------------------------------------------------------


class GoPackageSourcesField(MultipleSourcesField):
    default = ("*.go",)
    expected_file_extensions = (
        ".go",
        ".s",
        ".S",
        ".sx",
        ".c",
        ".h",
        ".hh",
        ".hpp",
        ".hxx",
        ".cc",
        ".cpp",
        ".cxx",
        ".m",
        ".f",
        ".F",
        ".for",
        ".f90",
        ".syso",
    )
    ban_subdirectories = True
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.go', '*_test.go', '!test_ignore.go']`"
    )

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], address: Address
    ) -> Optional[Tuple[str, ...]]:
        value_or_default = super().compute_value(raw_value, address)
        if not value_or_default:
            raise InvalidFieldException(
                f"The {repr(cls.alias)} field in target {address} must be set to files/globs in "
                f"the target's directory, but it was set to {repr(value_or_default)}."
            )
        return value_or_default


class GoPackageDependenciesField(Dependencies):
    pass


class SkipGoTestsField(BoolField):
    alias = "skip_tests"
    default = False
    help = "If true, don't run this package's tests."


class GoTestExtraEnvVarsField(TestExtraEnvVarsField):
    alias = "test_extra_env_vars"


class GoTestTimeoutField(TestTimeoutField):
    alias = "test_timeout"
    valid_numbers = ValidNumbers.positive_and_zero


class GoPackageTarget(Target):
    alias = "go_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        GoPackageDependenciesField,
        GoPackageSourcesField,
        GoTestExtraEnvVarsField,
        GoTestTimeoutField,
        GoTestRaceDetectorEnabledField,
        GoTestMemorySanitizerEnabledField,
        GoTestAddressSanitizerEnabledField,
        GoAssemblerFlagsField,
        GoCompilerFlagsField,
        SkipGoTestsField,
    )
    help = help_text(
        """
        A first-party Go package (corresponding to a directory with `.go` files).

        Expects that there is a `go_mod` target in its directory or in an ancestor
        directory.
        """
    )


# -----------------------------------------------------------------------------------------------
# `go_binary` target
# -----------------------------------------------------------------------------------------------


class GoBinaryMainPackageField(StringField, AsyncFieldMixin):
    alias = "main"
    help = help_text(
        """
        Address of the `go_package` with the `main` for this binary.

        If not specified, will default to the `go_package` for the same
        directory as this target's BUILD file. You should usually rely on this default.
        """
    )
    value: str


class GoBinaryDependenciesField(Dependencies):
    # This is only used to inject a dependency from the `GoBinaryMainPackageField`. Users should
    # add any explicit dependencies to the `go_package`.
    alias = "_dependencies"


class GoBinaryTarget(Target):
    alias = "go_binary"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        GoBinaryMainPackageField,
        GoBinaryDependenciesField,
        GoCgoEnabledField,
        GoRaceDetectorEnabledField,
        GoMemorySanitizerEnabledField,
        GoAddressSanitizerEnabledField,
        GoAssemblerFlagsField,
        GoCompilerFlagsField,
        GoLinkerFlagsField,
        RestartableField,
        EnvironmentField,
    )
    help = "A Go binary."


# -----------------------------------------------------------------------------------------------
# Support for codegen targets that need to specify an owning go_mod target
# -----------------------------------------------------------------------------------------------


class GoOwningGoModAddressField(StringField):
    alias = "go_mod_address"
    help = help_text(
        """
        Address of the `go_mod` target representing the Go module that this target is part of.

        This field is similar to the `resolve` field used in the Python and JVM backends. If a codegen
        target such as `protobuf_sources` will be used in multiple Go modules, then you should use
        the `parametrize` built-in to parametrize that `protobuf_sources` target for each Go module.

        If there is a single `go_mod` target in the repository, then this field defaults to the address
        for that single `go_mod` target.
        """
    )
