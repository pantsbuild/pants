# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.rust.subsystems.cargo import rules as cargo_rules
from pants.backend.rust.subsystems.rustc import rules as rustc_rules
from pants.backend.rust.rules.cargo_chroot import rules as cargo_chroot_rules
from pants.backend.rust.target_types import CargoProject


def rules():
    return [
        *cargo_rules(),
        *rustc_rules(),
        *cargo_chroot_rules(),
    ]


def target_types():
    return [
        CargoProject,
    ]
