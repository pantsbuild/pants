# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.scala.util_rules.versions import ScalaVersion
from pants.option.option_types import BoolOption, DictOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

DEFAULT_VERSION_MAPPING = {
    "2.13.6": "4.8.4",
    "2.13.7": "4.8.4",
    "2.13.8": "4.8.10",
    "2.13.9": "4.8.14",
    "2.13.10": "4.8.14",
    "2.13.11": "4.8.14",
    "2.13.12": "4.8.14",
}


class SemanticDbSubsystem(Subsystem):
    options_scope = "scalac-semanticdb"
    help = "semanticdb (ttps://scalameta.org/docs/semanticdb/)"

    enabled = BoolOption(
        default=True,
        help=softwrap(
            """
            Whether SemanticDB compilation should be enabled when compiling Scala sources.

            Please note that disabling SemanticDB may make other tools that require semantic
            compilation metadata not work properly (i.e. scalafix).
            """
        ),
    )

    _version_for_resolve = DictOption[str](
        help=softwrap(
            """
            A dictionary mapping the name of a resolve to the SemanticDB version to use for all Scala
            targets consuming that resolve.

            This is only required when working with Scala 2 as Scala 3 incorporates SemanticDB
            in the compiler.
            """
        )
    )

    extra_options = DictOption[str](help="Additional options to pass to the semanticdb compiler.")

    def version_for(self, resolve_name: str, scala_version: ScalaVersion) -> str | None:
        found_version = self._version_for_resolve.get(resolve_name)
        if not found_version:
            found_version = DEFAULT_VERSION_MAPPING.get(str(scala_version))
        return found_version
