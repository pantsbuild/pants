# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from typing import Sequence

from pants.core.goals.package import OutputPathField
from pants.engine.rules import collect_rules
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    InvalidFieldException,
    Sources,
    StringField,
    Target,
)


class GoSources(Sources):
    expected_file_extensions = (".go", ".s")


# -----------------------------------------------------------------------------------------------
# `go_package` target
# -----------------------------------------------------------------------------------------------


class GoPackageSources(GoSources):
    default = ("*.go", "*.s")


class GoImportPath(StringField):
    alias = "import_path"
    help = "Import path in Go code to import this package or module."


class GoPackageDependencies(Dependencies):
    pass


class GoPackage(Target):
    alias = "go_package"
    core_fields = (*COMMON_TARGET_FIELDS, GoPackageDependencies, GoPackageSources, GoImportPath)
    help = "A single Go package."


# -----------------------------------------------------------------------------------------------
# `go_mod` target
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


class GoModTarget(Target):
    alias = "go_mod"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        GoModSourcesField,
    )
    help = "A first-party Go module corresponding to a `go.mod` file."


# -----------------------------------------------------------------------------------------------
# `_go_external_package` target
# -----------------------------------------------------------------------------------------------


class GoExternalPackageDependencies(Dependencies):
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


class GoExternalPackageImportPathField(GoImportPath):
    required = True
    value: str


class GoExternalPackageTarget(Target):
    alias = "_go_external_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        GoExternalPackageDependencies,
        GoExternalModulePathField,
        GoExternalModuleVersionField,
        GoExternalPackageImportPathField,
    )
    help = "A package from a third-party Go module."


# -----------------------------------------------------------------------------------------------
# `go_binary` target
# -----------------------------------------------------------------------------------------------


class GoBinaryMainAddress(StringField):
    alias = "main"
    required = True
    help = "Address of the main Go package for this binary."
    value: str


class GoBinary(Target):
    alias = "go_binary"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, OutputPathField, GoBinaryMainAddress)
    help = "A Go binary."


def rules():
    return collect_rules()
