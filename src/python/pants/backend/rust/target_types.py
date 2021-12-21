# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, MultipleSourcesField, Target


class RustCrateSourcesField(MultipleSourcesField):
    default = ("Cargo.toml", "src/**/*.rs", "tests/**/*.rs")


class RustCrateTarget(Target):
    alias = "rust_crate"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        RustCrateSourcesField,
        Dependencies,
    )
    help = "A Rust crate"
