# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem


class SoapSubsystem(Subsystem):
    options_scope = "soap"
    help = "General SOAP/WSDL codegen settings."

    tailor = BoolOption(
        default=True,
        help="If true, add `wsdl_sources` targets with the `tailor` goal.",
        advanced=True,
    )
