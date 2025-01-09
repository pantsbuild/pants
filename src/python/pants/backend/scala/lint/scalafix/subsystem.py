# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.core.util_rules.config_files import OrphanFilepathConfigBehavior
from pants.engine.addresses import UnparsedAddressInputs
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import BoolOption, EnumOption, SkipOption, StrListOption, StrOption
from pants.util.memo import memoized_property
from pants.util.strutil import softwrap

DEFAULT_SCALAFIX_CONFIG_FILENAME = ".scalafix.conf"


class ScalafixSubsystem(JvmToolBase):
    options_scope = "scalafix"
    name = "scalafix"
    help = "scalafix (https://scalacenter.github.io/scalafix/)"

    default_version = "0.11.1"
    default_artifacts = ("ch.epfl.scala:scalafix-cli_2.13.12:{version}",)
    default_lockfile_resource = (
        "pants.backend.scala.lint.scalafix",
        "scalafix.default.lockfile.txt",
    )

    config_file_name = StrOption(
        default=DEFAULT_SCALAFIX_CONFIG_FILENAME,
        advanced=True,
        help=softwrap(
            """
            Name of a config file understood by scalafix (https://scalacenter.github.io/scalafix/docs/users/configuration.html).
            The plugin will search the ancestors of each directory in which Scala files are found for a config file of this name.
            """
        ),
    )

    orphan_files_behavior = EnumOption(
        default=OrphanFilepathConfigBehavior.ERROR,
        advanced=True,
        help=softwrap(
            f"""
            Whether to ignore, error or show a warning when files are found that are not
            covered by the config file provided in `[{options_scope}].config_file_name` setting.
            """
        ),
    )

    semantic_rules = BoolOption(
        default=True,
        advanced=True,
        help=softwrap(
            """
            Whether semantic rules are enabled or not.

            Using semantic rules requires the usage of the `semanticdb-scalac` plugin
            and will trigger compilation of the source code before running scalafix on
            the sources.
            """
        ),
    )

    _rule_targets = StrListOption(
        advanced=True, help="List of targets providing additional Scalafix rules."
    )

    skip = SkipOption("fix", "lint")

    @memoized_property
    def rule_targets(self) -> UnparsedAddressInputs | None:
        if not self._rule_targets:
            return None

        return UnparsedAddressInputs(
            self._rule_targets,
            owning_address=None,
            description_of_origin=f"the `[{self.options_scope}].extra_rule_targets` subsystem option",
        )
