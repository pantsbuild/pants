# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem


class AvroSubsystem(Subsystem):
    options_scope = "avro"
    help = "General Avro codegen settings."

    tailor = BoolOption(
        default=True,
        help="If true, add `avro_sources` targets with the `tailor` goal.",
        advanced=True,
    )
