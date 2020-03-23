# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.subsystem.subsystem import Subsystem


class PantsTestutilSubsystem(Subsystem):
    options_scope = "pants-testutil"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--requirement-target",
            advanced=True,
            fingerprint=True,
            help="Address for a python target providing the pants sdist.",
            type=str,
            default=None,
        )
        register(
            "--testutil-target",
            advanced=True,
            fingerprint=True,
            help="Address for a python target providing the " "pants testutil sdist.",
            type=str,
            default=None,
        )

    def dependent_target_addrs(self):
        return [
            self.get_options().requirement_target,
            self.get_options().testutil_target,
        ]
