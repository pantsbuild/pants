# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Iterable, Optional, Sequence, Tuple

from pants.core.goals.package import OutputPathField
from pants.core.goals.run import RestartableField
from pants.core.goals.test import TestExtraEnvVarsField, TestTimeoutField
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
    Target,
    TargetGenerator,
    TriBoolField,
    ValidNumbers,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import softwrap

# -----------------------------------------------------------------------------------------------
# Build option fields
# -----------------------------------------------------------------------------------------------


class GoCgoEnabledField(TriBoolField):
    """Enables Cgo support."""

    alias = "cgo_enabled"
    help = softwrap(
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
    help = softwrap(
        """
        Enable compiling the binary with the Go data race detector.

        See https://go.dev/doc/articles/race_detector for additional information about the Go data race detector.
        """
    )


class GoTestRaceDetectorEnabledField(GoRaceDetectorEnabledField):
    alias = "test_race"
    help = softwrap(
        """
        Enable compiling this package's test binary with the Go data race detector.

        See https://go.dev/doc/articles/race_detector for additional information about the Go data race detector.
        """
    )


class GoMemorySanitizerEnabledField(TriBoolField):
    """Enables the C/C++ memory sanitizer."""

    alias = "msan"
    help = softwrap(
        """
        Enable interoperation between Go code and the C/C++ "memory sanitizer."

        See https://github.com/google/sanitizers/wiki/MemorySanitizer for additional information about
        the C/C++ memory sanitizer.
        """
    )


class GoTestMemorySanitizerEnabledField(GoRaceDetectorEnabledField):
    alias = "test_msan"
    help = softwrap(
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
    help = softwrap(
        """
        Enable interoperation between Go code and the C/C++ "address sanitizer."

        See https://github.com/google/sanitizers/wiki/AddressSanitizer for additional information about
        the C/C++ address sanitizer.
        """
    )


class GoTestAddressSanitizerEnabledField(GoRaceDetectorEnabledField):
    alias = "test_asan"
    help = softwrap(
        """
        Enable interoperation between Go code and the C/C++ "address sanitizer" when building this package's
        test binary.

        See https://github.com/google/sanitizers/wiki/AddressSanitizer for additional information about
        the C/C++ address sanitizer.
        """
    )


# -----------------------------------------------------------------------------------------------
# `go_third_party_package` target
# -----------------------------------------------------------------------------------------------


class GoImportPathField(StringField):
    alias = "import_path"
    help = softwrap(
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
    help = softwrap(
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
    help = softwrap(
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
        SkipGoTestsField,
    )
    help = softwrap(
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
    help = softwrap(
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
        RestartableField,
    )
    help = "A Go binary."


# -----------------------------------------------------------------------------------------------
# Support for codegen targets that need to specify an owning go_mod target
# -----------------------------------------------------------------------------------------------


class GoOwningGoModAddressField(StringField):
    alias = "go_mod_address"
    help = softwrap(
        """
        Address of the `go_mod` target representing the Go module that this target is part of.

        This field is similar to the `resolve` field used in the Python and JVM backends. If a codegen
        target such as `protobuf_sources` will be used in multiple Go modules, then you should use
        the `parametrize` built-in to parametrize that `protobuf_sources` target for each Go module.

        If there is a single `go_mod` target in the repository, then this field defaults to the address
        for that single `go_mod` target.
        """
    )
