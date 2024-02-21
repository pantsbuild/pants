# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.option.option_types import BoolOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)

_telemetry_docs_referral = f"See {doc_url('docs/using-pants/anonymous-telemetry')} for details"


# This subsystem is orphaned (but not quite deprecated/removed).
# We found that:
#   - Most people disabled the telemetry
#   - The telemetry we received wasn't being used for meaningful decisions
#   - The implementation we had required humbug, which bloated Pants' environment with it and its dependencies
#
# The subsystem still exists, however, in hopes that a future implementation could be added seamlessly
# which addresses the above points.
class AnonymousTelemetry(Subsystem):
    options_scope = "anonymous-telemetry"
    help = "Options related to sending anonymous stats to the Pants project, to aid development."

    enabled = BoolOption(
        default=False,
        help=softwrap(
            f"""
            Whether to send anonymous telemetry to the Pants project.

            Telemetry is sent asynchronously, with silent failure, and does not impact build times
            or outcomes.

            {_telemetry_docs_referral}.
            """
        ),
        advanced=True,
    )
    repo_id = StrOption(
        default=None,
        help=softwrap(
            f"""
            An anonymized ID representing this repo.

            For private repos, you likely want the ID to not be derived from, or algorithmically
            convertible to, anything identifying the repo.

            For public repos the ID may be visible in that repo's config file, so anonymity of the
            repo is not guaranteed (although user anonymity is always guaranteed).

            {_telemetry_docs_referral}.
            """
        ),
        advanced=True,
    )


def rules():
    return AnonymousTelemetry.rules()
