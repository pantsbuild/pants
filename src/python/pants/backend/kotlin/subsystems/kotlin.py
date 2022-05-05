# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.option.option_types import BoolOption, DictOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

DEFAULT_KOTLIN_VERSION = "1.6.20"

_logger = logging.getLogger(__name__)


class KotlinSubsystem(Subsystem):
    options_scope = "kotlin"
    name = "kotlin"
    help = "The Kotlin programming language (https://kotlinlang.org/)."

    _version_for_resolve = DictOption[str](
        "--version-for-resolve",
        help=softwrap(
            """
            A dictionary mapping the name of a resolve to the Kotlin version to use for all Kotlin
            targets consuming that resolve.
            """
        ),
    )
    tailor_source_targets = BoolOption(
        "--tailor-source-targets",
        default=True,
        help="If true, add `kotlin_sources` targets with the `tailor` goal.",
        advanced=True,
    )

    def version_for_resolve(self, resolve: str) -> str:
        version = self._version_for_resolve.get(resolve)
        if version:
            return version
        return DEFAULT_KOTLIN_VERSION
