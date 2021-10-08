# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

from pants.core.goals.package import OutputPathField
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import GlobExpansionConjunction, GlobMatchErrorBehavior, PathGlobs
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    Dependencies,
    InvalidFieldException,
    Sources,
    StringField,
    StringSequenceField,
    Target,
)
from pants.option.global_options import FilesNotFoundBehavior


class GoImportPathField(StringField):
    alias = "import_path"
    help = "Import path in Go code to import this package."
    required = True
    value: str


def is_first_party_package_target(tgt: Target) -> bool:
    return tgt.has_field(GoInternalPackageSourcesField)


def is_third_party_package_target(tgt: Target) -> bool:
    return tgt.has_field(GoExternalPackageDependenciesField)


# -----------------------------------------------------------------------------------------------
# `go_mod` target generator
# -----------------------------------------------------------------------------------------------


class GoModSourcesField(Sources):
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
    alias = "pkg_sources"
    default = ("**/*.go", "**/*.s")
    help = (
        "What sources to generate `_go_internal_package` targets for.\n\n"
        "Pants will generate one target per matching directory."
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
        "A first-party Go module corresponding to a `go.mod` file.\n\n"
        "Generates `_go_internal_package` targets for each directory from the "
        "`internal_pkg_sources` field, and generates `_go_external_package` targets based on "
        "the `require` directives in your `go.mod`.\n\n"
        "If you have external packages, make sure you have an up-to-date `go.sum`. Run "
        "`go mod tidy` directly to update your `go.mod` and `go.sum`."
    )


# -----------------------------------------------------------------------------------------------
# `_go_internal_package` target
# -----------------------------------------------------------------------------------------------


class GoInternalPackageSourcesField(Sources):
    expected_file_extensions = (".go", ".s")


class GoInternalPackageDependenciesField(Dependencies):
    pass


class GoInternalPackageSubpathField(StringField, AsyncFieldMixin):
    alias = "subpath"
    help = (
        "The path from the owning `go.mod` to this package's directory, e.g. `subdir`.\n\n"
        "Should not include a leading `./`. If the package is in the same directory as the "
        "`go.mod`, use the empty string."
    )
    required = True
    value: str

    @property
    def full_dir_path(self) -> str:
        """The full path to this package's directory, relative to the build root."""
        # NB: Assumes that the `spec_path` points to the ancestor `go.mod`, which will be the
        # case when `go_mod` targets generate.
        if not self.address.is_generated_target:
            # TODO: Make this error more eager via target validation.
            raise AssertionError(
                f"Target was manually created, but expected to be generated: {self.address}"
            )
        go_mod_path = self.address.spec_path
        if not self.value:
            return go_mod_path
        return os.path.join(go_mod_path, self.value)


class GoInternalPackageTarget(Target):
    alias = "_go_internal_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        GoImportPathField,
        GoInternalPackageSubpathField,
        GoInternalPackageDependenciesField,
        GoInternalPackageSourcesField,
    )
    help = "A single Go package."


# -----------------------------------------------------------------------------------------------
# `_go_external_package` target
# -----------------------------------------------------------------------------------------------


class GoExternalPackageDependenciesField(Dependencies):
    pass


class GoExternalModulePathField(StringField):
    alias = "path"
    help = (
        "The module path of the third-party module this package comes from, "
        "e.g. `github.com/google/go-cmp`."
    )
    required = True
    value: str


class GoExternalModuleVersionField(StringField):
    alias = "version"
    help = "The version of the third-party module this package comes from, e.g. `v0.4.0`."
    required = True
    value: str


class GoExternalPackageTarget(Target):
    alias = "_go_external_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        GoExternalPackageDependenciesField,
        GoExternalModulePathField,
        GoExternalModuleVersionField,
        GoImportPathField,
    )
    help = "A package from a third-party Go module."


# -----------------------------------------------------------------------------------------------
# `go_binary` target
# -----------------------------------------------------------------------------------------------


class GoBinaryMainPackageField(StringField, AsyncFieldMixin):
    alias = "main"
    help = (
        "Address of the `_go_internal_package` with the `main` for this binary.\n\n"
        "If not specified, will default to the `_go_internal_package` for the same "
        "directory as this target's BUILD file."
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
    )
    help = "A Go binary."
