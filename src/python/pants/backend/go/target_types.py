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
    help = "Import path in Go code to import this package."


class GoPackage(Target):
    alias = "go_package"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, GoPackageSources, GoImportPath)
    help = "A single Go package."


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
