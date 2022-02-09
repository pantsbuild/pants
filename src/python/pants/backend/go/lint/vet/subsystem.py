# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import cast

from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name


class GoVetSubsystem(Subsystem):
    options_scope = "go-vet"
    help = "`go vet`-specific options."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=f"Don't use `go vet` when running `{bin_name()} lint`.",
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)
