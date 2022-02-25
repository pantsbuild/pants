# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name


class GoVetSubsystem(Subsystem):
    options_scope = "go-vet"
    help = "`go vet`-specific options."

    skip = BoolOption(
        "--skip",
        default=False,
        help=f"Don't use `go vet` when running `{bin_name()} lint`.",
    )
