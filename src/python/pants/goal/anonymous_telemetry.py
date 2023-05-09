# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.option.option_types import BoolOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class AnonymousTelemetry(Subsystem):
    options_scope = "anonymous-telemetry"
    help = "<DEPRECATED>"

    enabled = BoolOption(
        default=False,
        removal_version="2.18.0.dev0",
        removal_hint=softwrap(
            """
            `anonymous-telemetry` is deprecated in 2.17 and will be removed in 2.18. We no longer
            send any telemetry information whether this is enabled or disabled.

            (Additionally, we no longer warn when this option isn't provided)
            """
        ),
        help="<DEPRECATED>",
        advanced=True,
    )
    repo_id = StrOption(
        default=None,
        removal_version="2.18.0.dev0",
        removal_hint=softwrap(
            "`anonymous-telemetry` is deprecated in 2.17 and will be removed in 2.18."
        ),
        help="<DEPRECATED>",
        advanced=True,
    )


def rules():
    return AnonymousTelemetry.rules()
