# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.rust.goals import tailor
from pants.backend.rust.lint.rustfmt.rules import rules as rustfmt_rules
from pants.backend.rust.target_types import RustPackageTarget
from pants.backend.rust.util_rules import toolchains


def target_types():
    return (RustPackageTarget,)


def rules():
    return (
        *tailor.rules(),
        *toolchains.rules(),
        *rustfmt_rules(),
    )
