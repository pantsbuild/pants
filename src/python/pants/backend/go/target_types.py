# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.engine.rules import collect_rules
from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Sources, StringField, Target


class GoSources(Sources):
    expected_file_extensions = (".go",)


class GoPackageSources(GoSources):
    default = ("*.go", "!*_test.go")


class GoImportPath(StringField):
    # TODO: Infer the import path from the closest ancestor `go_module` target once that target is supported.
    alias = "import_path"
    help = "Import path in Go code to import this package or module."


class GoPackageDependencies(Dependencies):
    pass


class GoPackage(Target):
    alias = "go_package"
    core_fields = (*COMMON_TARGET_FIELDS, GoPackageDependencies, GoPackageSources, GoImportPath)
    help = "A single Go package."


# `go_module` target


class GoModuleGoVersion(StringField):
    alias = "go_version"
    # TODO: Set default to match the active `GoLangDisribution`.
    default = "1.16"


# class GoModuleGoModSource(Sources):
#     alias = "gomod"
#     default = ["go.mod"]
#     # TODO: This does not handle a missing go.mod file.
#     expected_num_files = 1
#
#
# class GoModuleGoSumSource(Sources):
#     alias = "gosum"
#     default = ["go.sum"]
#     # TODO: This does not handle a missing go.sum file.
#     expected_num_files = 1
#     help = "The source file containing the go.sum file."
#
#
# class GoModuleImportPathReplacements(StringSequenceField):
#     alias = "replacements"
#     help = (
#         "Import path replacements where each item is in the form ORIGINAL,REPLACEMENT. "
#         "This will be inferred from the go.mod file."
#     )


class GoModule(Target):
    alias = "go_module"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        GoModuleGoVersion,
        GoImportPath,
        # GoModuleGoModSource,
        # GoModuleGoSumSource,
    )


# `go_external_module`


class GoExternalModulePath(StringField):
    alias = "path"


class GoExternalModuleVersion(StringField):
    alias = "version"


class GoExternalModule(Target):
    alias = "go_external_module"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        GoExternalModulePath,
        GoExternalModuleVersion,
        GoImportPath,
    )


# `go_binary` target


class GoBinaryName(StringField):
    alias = "binary_name"
    required = True
    help = "Name of the Go binary to output."


class GoBinaryMainAddress(StringField):
    alias = "main"
    required = True
    help = "Address of the main Go package for this binary."


# TODO: This should register `OutputPathField` instead of `GoBinaryName`. (And then update build.py.)
class GoBinary(Target):
    alias = "go_binary"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, GoBinaryName, GoBinaryMainAddress)
    help = "A Go binary."


def rules():
    return collect_rules()
