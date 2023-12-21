# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.scala.subsystems.scala import DEFAULT_SCALA_VERSION
from pants.engine.addresses import UnparsedAddressInputs
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import SkipOption, StrListOption, StrOption
from pants.util.memo import memoized_property

DEFAULT_SCALAFIX_CONFIG_FILENAME = ".scalafix.conf"


class ScalafixSubsystem(JvmToolBase):
    options_scope = "scalafix"
    name = "scalafix"
    help = "scalafix (https://scalacenter.github.io/scalafix/)"

    default_version = "0.11.1"
    default_artifacts = (f"ch.epfl.scala:scalafix-cli_{DEFAULT_SCALA_VERSION}:{{version}}",)
    default_lockfile_resource = (
        "pants.backend.scala.lint.scalafix",
        "scalafix.default.lockfile.txt",
    )

    config_filename = StrOption(
        default=DEFAULT_SCALAFIX_CONFIG_FILENAME,
        help="Name to look for when locating scalafix config files.",
    )
    _extra_rule_targets = StrListOption(help="List of targets providing additional Scalafix rules.")

    skip = SkipOption("fix", "lint")

    @memoized_property
    def extra_rule_targets(self) -> UnparsedAddressInputs | None:
        if not self._extra_rule_targets:
            return None

        return UnparsedAddressInputs(
            self._extra_rule_targets,
            owning_address=None,
            description_of_origin=f"the `[{self.options_scope}].extra_rule_targets` subsystem option",
        )
