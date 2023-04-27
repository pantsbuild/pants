# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import COMMON_TARGET_FIELDS, MultipleSourcesField, Target, \
    SingleSourceField


class CargoTomlSourceField(SingleSourceField):
    default = "Cargo.toml"


class RustWorkspaceTarget(Target):
    alias = "rust_workspace"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CargoTomlSourceField,
    )


class RustPackageTarget(Target):
    alias = "rust_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CargoTomlSourceField,
    )


class RustCrateSourcesField(MultipleSourcesField):
    default = ("Cargo.toml", "src/**/*.rs", "tests/**/*.rs")
    uses_source_roots = False


class RustCrateTarget(Target):
    alias = "rust_crate"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        RustCrateSourcesField,
    )
    help = "A Rust crate. This must not be made manually, but only via target generation."
