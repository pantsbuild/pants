# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem


class GoVetSubsystem(Subsystem):
    options_scope = "go-vet"
    help = "`go vet`-specific options."

    skip = BoolOption(
        "--skip",
        default=False,
        help=("Don't use gofmt when running `./pants fmt` and `./pants lint`."),
    )
