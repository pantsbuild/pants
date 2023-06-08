# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import COMMON_TARGET_FIELDS, MultipleSourcesField, Target
from pants.util.strutil import help_text


class RustPackageSourcesField(MultipleSourcesField):
    default = ("src/**/*.rs", "tests/**/*.rs")
    uses_source_roots = False


class RustPackageTarget(Target):
    alias = "rust_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        RustPackageSourcesField,
    )
    help = help_text(
        """
        A Rust package as defined in https://doc.rust-lang.org/book/ch07-01-packages-and-crates.html.

        Expects that there is a `Cargo.toml` target in its root directory
        """
    )
