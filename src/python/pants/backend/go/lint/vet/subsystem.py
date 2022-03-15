# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem


class GoVetSubsystem(Subsystem):
    options_scope = "go-vet"
    name = "`go vet`"
    help = "`go vet`-specific options."

    skip = SkipOption("lint")
