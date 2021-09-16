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
    expected_file_extensions = (".go",)


# -----------------------------------------------------------------------------------------------
# `go_package` target
# -----------------------------------------------------------------------------------------------


class GoPackageSources(GoSources):
    default = ("*.go",)


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
# `go_module` target
# -----------------------------------------------------------------------------------------------


class GoModuleSources(Sources):
    alias = "_sources"
    default = ("go.mod", "go.sum")
    expected_num_files = range(1, 3)

    def validate_resolved_files(self, files: Sequence[str]) -> None:
        super().validate_resolved_files(files)
        if "go.mod" not in [os.path.basename(f) for f in files]:
            raise InvalidFieldException(f"""No go.mod file was found for target {self.address}.""")


class GoModule(Target):
    alias = "go_module"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        GoModuleSources,
    )
    help = "First-party Go module."


# -----------------------------------------------------------------------------------------------
# `_go_external_package` target
# -----------------------------------------------------------------------------------------------


class GoExtModPackageDependencies(Dependencies):
    pass


class GoExternalModulePath(StringField):
    alias = "path"
    help = "Module path to a Go module"


class GoExternalModuleVersion(StringField):
    alias = "version"
    help = "Version of a Go module."


class GoExternalPackageTarget(Target):
    alias = "_go_external_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        GoExtModPackageDependencies,
        GoExternalModulePath,
        GoExternalModuleVersion,
        GoImportPath,
    )
    help = "Package in an external Go module."


# -----------------------------------------------------------------------------------------------
# `go_binary` target
# -----------------------------------------------------------------------------------------------


class GoBinaryMainAddress(StringField):
    alias = "main"
    required = True
    help = "Address of the main Go package for this binary."


class GoBinary(Target):
    alias = "go_binary"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, OutputPathField, GoBinaryMainAddress)
    help = "A Go binary."


def rules():
    return collect_rules()
