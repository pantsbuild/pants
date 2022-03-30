# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

from pants.core.goals.package import OutputPathField
from pants.core.goals.run import RestartableField
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    BoolField,
    Dependencies,
    IntField,
    InvalidFieldException,
    InvalidTargetException,
    MultipleSourcesField,
    StringField,
    Target,
    TargetGenerator,
    ValidNumbers,
)

# -----------------------------------------------------------------------------------------------
# `go_third_party_package` target
# -----------------------------------------------------------------------------------------------


class GoImportPathField(StringField):
    alias = "import_path"
    help = (
        "Import path in Go code to import this package.\n\n"
        "This field should not be overridden; use the value from target generation."
    )
    required = True
    value: str


class GoThirdPartyPackageDependenciesField(Dependencies):
    pass


class GoThirdPartyPackageTarget(Target):
    alias = "go_third_party_package"
    core_fields = (*COMMON_TARGET_FIELDS, GoThirdPartyPackageDependenciesField, GoImportPathField)
    help = (
        "A package from a third-party Go module.\n\n"
        "You should not explicitly create this target in BUILD files. Instead, add a `go_mod` "
        "target where you have your `go.mod` file, which will generate "
        "`go_third_party_package` targets for you.\n\n"
        "Make sure that your `go.mod` and `go.sum` files include this package's module."
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
    help = (
        "A first-party Go module (corresponding to a `go.mod` file).\n\n"
        "Generates `go_third_party_package` targets based on the `require` directives in your "
        "`go.mod`.\n\n"
        "If you have third-party packages, make sure you have an up-to-date `go.sum`. Run "
        "`go mod tidy` directly to update your `go.mod` and `go.sum`."
    )
    generated_target_cls = GoThirdPartyPackageTarget
    core_fields = (
        *COMMON_TARGET_FIELDS,
        GoModDependenciesField,
        GoModSourcesField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = ()


# -----------------------------------------------------------------------------------------------
# `go_package` target
# -----------------------------------------------------------------------------------------------


class GoPackageSourcesField(MultipleSourcesField):
    default = ("*.go", "*.s")
    expected_file_extensions = (".go", ".s")

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

        # Ban recursive globs and subdirectories. We assume that a `go_package` corresponds
        # to exactly one directory.
        invalid_globs = [
            glob for glob in (value_or_default or ()) if "**" in glob or os.path.sep in glob
        ]
        if invalid_globs:
            raise InvalidFieldException(
                f"The {repr(cls.alias)} field in target {address} must only have globs for the "
                f"target's directory, i.e. it cannot include values with `**` and `{os.path.sep}`, "
                f"but it was set to: {sorted(value_or_default)}"
            )
        return value_or_default


class GoPackageDependenciesField(Dependencies):
    pass


class SkipGoTestsField(BoolField):
    alias = "skip_tests"
    default = False
    help = "If true, don't run this package's tests."


class GoTestTimeoutField(IntField):
    alias = "test_timeout"
    help = (
        "A timeout (in seconds) when running this package's tests.\n\n"
        "If this field is not set, the test will never time out."
    )
    valid_numbers = ValidNumbers.positive_and_zero


class GoPackageTarget(Target):
    alias = "go_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        GoPackageDependenciesField,
        GoPackageSourcesField,
        GoTestTimeoutField,
        SkipGoTestsField,
    )
    help = (
        "A first-party Go package (corresponding to a directory with `.go` files).\n\n"
        "Expects that there is a `go_mod` target in its directory or in an ancestor "
        "directory."
    )


# -----------------------------------------------------------------------------------------------
# `go_binary` target
# -----------------------------------------------------------------------------------------------


class GoBinaryMainPackageField(StringField, AsyncFieldMixin):
    alias = "main"
    help = (
        "Address of the `go_package` with the `main` for this binary.\n\n"
        "If not specified, will default to the `go_package` for the same "
        "directory as this target's BUILD file. You should usually rely on this default."
    )
    value: str


@dataclass(frozen=True)
class GoBinaryMainPackage:
    address: Address


@dataclass(frozen=True)
class GoBinaryMainPackageRequest(EngineAwareParameter):
    field: GoBinaryMainPackageField

    def debug_hint(self) -> str:
        return self.field.address.spec


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
        RestartableField,
    )
    help = "A Go binary."
