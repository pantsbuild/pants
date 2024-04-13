# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.rust.target_types import RustPackageTarget
from pants.engine.target import BoolField


class SkipRustfmtField(BoolField):
    alias = "skip_rustfmt"
    default = False
    help = "If true, don't run rustfmt on this crate."


def rules():
    return [RustPackageTarget.register_plugin_field(SkipRustfmtField)]
