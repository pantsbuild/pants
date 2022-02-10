# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from typing import cast

from pants.option.option_types import StrOption
from pants.option.subsystem import Subsystem

DEFAULT_SCALA_VERSION = "2.13.6"

_logger = logging.getLogger(__name__)


class ScalaSubsystem(Subsystem):
    options_scope = "scala"
    help = "Scala programming language"

    version = StrOption(
        "--version",
        default=DEFAULT_SCALA_VERSION,
        help=(
            "The version of Scala to use.\n\n"
            "This option is deprecated in favor of the `[scala].version_for_resolve` option. If "
            "`[scala].version_for_resolve` does not have an entry for a resolve, then the value of "
            "this option will be used as the Scala version for that resolve."
        ),
    ).deprecated(removal_version="2.11.0.dev0", hint="Use `[scala].version_for_resolve` instead.")

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--version-for-resolve",
            type=dict,
            help=(
                "A dictionary mapping the name of a resolve to the Scala version to use for all Scala "
                "targets consuming that resolve.\n\n"
                'All Scala-compiled jars on a resolve\'s classpath must be "compatible" with one another and '
                "with all Scala-compiled first-party sources from `scala_sources` (and other Scala target types) "
                "using that resolve. The option sets the Scala version that will be used to compile all "
                "first-party sources using the resolve. This ensures that the compatibility property is "
                "maintained for a resolve. To support multiple Scala versions, use multiple resolves."
            ),
        )

    @property
    def _version_for_resolve(self) -> dict[str, str]:
        return cast("dict[str, str]", self.options.version_for_resolve)

    def version_for_resolve(self, resolve: str):
        version = self._version_for_resolve.get(resolve)
        if version:
            return version
        return self.version
