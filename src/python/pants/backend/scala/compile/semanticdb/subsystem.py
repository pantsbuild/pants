# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.scala.util_rules.versions import ScalaVersion
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import DictOption, StrOption
from pants.option.subsystem import Subsystem


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

    _version_mapping = DictOption[str](default=DEFAULT_VERSION_MAPPING, help="Version mapping from Scala version to SemanticDB version.")

    extra_options = DictOption[str](help="Additional options to pass to semanticdb compiler.")

    def version_for_scala(self, scala_version: ScalaVersion) -> str | None:
      return self._version_mapping.get(str(scala_version))
