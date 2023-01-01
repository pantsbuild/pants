# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.option.option_types import BoolOption, DictOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

DEFAULT_SCALA_VERSION = "2.13.6"

_logger = logging.getLogger(__name__)


class ScalaSubsystem(Subsystem):
    options_scope = "scala"
    help = "Scala programming language"

    _version_for_resolve = DictOption[str](
        help=softwrap(
            """
            A dictionary mapping the name of a resolve to the Scala version to use for all Scala
            targets consuming that resolve.

            All Scala-compiled jars on a resolve\'s classpath must be "compatible" with one another and
            with all Scala-compiled first-party sources from `scala_sources` (and other Scala target types)
            using that resolve. The option sets the Scala version that will be used to compile all
            first-party sources using the resolve. This ensures that the compatibility property is
            maintained for a resolve. To support multiple Scala versions, use multiple resolves.
            """
        ),
    )
    tailor_source_targets = BoolOption(
        default=True,
        help=softwrap(
            """
            If true, add `scala_sources`, `scala_junit_tests`, and `scalatest_tests` targets with
            the `tailor` goal."""
        ),
        advanced=True,
    )

    def version_for_resolve(self, resolve: str) -> str:
        version = self._version_for_resolve.get(resolve)
        if version:
            return version
        return DEFAULT_SCALA_VERSION
