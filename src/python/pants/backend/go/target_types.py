# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

from pants.core.goals.package import OutputPathField
from pants.core.goals.run import RestartableField
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import GlobExpansionConjunction, GlobMatchErrorBehavior, PathGlobs
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    Dependencies,
    InvalidFieldException,
    InvalidTargetException,
    MultipleSourcesField,
    StringField,
    StringSequenceField,
    Target,
)
from pants.option.global_options import FilesNotFoundBehavior


class GoImportPathField(StringField):
    alias = "import_path"
    help = (
        "Import path in Go code to import this package.\n\n"
        "This field should not be overridden; use the value from target generation."
    )
    required = True
    value: str


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


# TODO(#12953): generalize this?
class GoModPackageSourcesField(StringSequenceField, AsyncFieldMixin):
    alias = "package_sources"
    default = ("**/*.go", "**/*.s")
    help = (
        "What sources to generate `go_first_party_package` targets for.\n\n"
        "Pants will generate one target per matching directory.\n\n"
        "Pants does not yet support some file types like `.c` and `.h` files, along with cgo "
        "files. If you need to use these files, please open a feature request at "
        "https://github.com/pantsbuild/pants/issues/new/choose so that we know to "
        "prioritize adding support."
    )

    def _prefix_glob_with_address(self, glob: str) -> str:
        if glob.startswith("!"):
            return f"!{os.path.join(self.address.spec_path, glob[1:])}"
        return os.path.join(self.address.spec_path, glob)

    def path_globs(self, files_not_found_behavior: FilesNotFoundBehavior) -> PathGlobs:
        error_behavior = files_not_found_behavior.to_glob_match_error_behavior()
        return PathGlobs(
            (self._prefix_glob_with_address(glob) for glob in self.value or ()),
            conjunction=GlobExpansionConjunction.any_match,
            glob_match_error_behavior=error_behavior,
            description_of_origin=(
                f"{self.address}'s `{self.alias}` field"
                if error_behavior != GlobMatchErrorBehavior.ignore
                else None
            ),
        )


class GoModTarget(Target):
    alias = "go_mod"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        GoModDependenciesField,
        GoModSourcesField,
        GoModPackageSourcesField,
    )
    help = (
        "A first-party Go module (corresponding to a `go.mod` file).\n\n"
        "Generates `go_first_party_package` targets for each directory from the "
        "`package_sources` field, and generates `go_third_party_package` targets based on "
        "the `require` directives in your `go.mod`.\n\n"
        "If you have third-party packages, make sure you have an up-to-date `go.sum`. Run "
        "`go mod tidy` directly to update your `go.mod` and `go.sum`."
    )


# -----------------------------------------------------------------------------------------------
# `go_first_party_package` target
# -----------------------------------------------------------------------------------------------


class GoFirstPartyPackageSourcesField(MultipleSourcesField):
    expected_file_extensions = (".go", ".s")


class GoFirstPartyPackageDependenciesField(Dependencies):
    pass


class GoFirstPartyPackageSubpathField(StringField, AsyncFieldMixin):
    alias = "subpath"
    help = (
        "The path from the owning `go.mod` to this package's directory, e.g. `subdir`.\n\n"
        "This field should not be overridden; use the value from target generation."
    )
    required = True
    value: str


class GoFirstPartyPackageTarget(Target):
    alias = "go_first_party_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        GoImportPathField,
        GoFirstPartyPackageSubpathField,
        GoFirstPartyPackageDependenciesField,
        GoFirstPartyPackageSourcesField,
    )
    help = (
        "A Go package (corresponding to a directory with `.go` files).\n\n"
        "You should not explicitly create this target in BUILD files. Instead, add a `go_mod` "
        "target where you have your `go.mod` file, which will generate "
        "`go_first_party_package` targets for you."
    )

    def validate(self) -> None:
        if not self.address.is_generated_target:
            raise InvalidTargetException(
                f"The `{self.alias}` target type should not be manually created in BUILD "
                f"files, but it was created for {self.address}.\n\n"
                "Instead, add a `go_mod` target where you have your `go.mod` file, which will "
                f"generate `{self.alias}` targets for you."
            )


# -----------------------------------------------------------------------------------------------
# `go_third_party_package` target
# -----------------------------------------------------------------------------------------------


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
# `go_binary` target
# -----------------------------------------------------------------------------------------------


class GoBinaryMainPackageField(StringField, AsyncFieldMixin):
    alias = "main"
    help = (
        "Address of the `go_first_party_package` with the `main` for this binary.\n\n"
        "If not specified, will default to the `go_first_party_package` for the same "
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
