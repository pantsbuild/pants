# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.config_files import OrphanFilepathConfigBehavior
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import EnumOption, SkipOption, StrOption
from pants.util.strutil import softwrap

DEFAULT_SCALAFMT_CONF_FILENAME = ".scalafmt.conf"


class ScalafmtSubsystem(JvmToolBase):
    options_scope = "scalafmt"
    name = "scalafmt"
    help = "scalafmt (https://scalameta.org/scalafmt/)"

    default_version = "3.2.1"
    default_artifacts = ("org.scalameta:scalafmt-cli_2.13:{version}",)
    default_lockfile_resource = (
        "pants.backend.scala.lint.scalafmt",
        "scalafmt.default.lockfile.txt",
    )

    config_file_name = StrOption(
        "--config-file-name",
        default=DEFAULT_SCALAFMT_CONF_FILENAME,
        advanced=True,
        help=softwrap(
            """
            Name of a config file understood by scalafmt (https://scalameta.org/scalafmt/docs/configuration.html).
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

    skip = SkipOption("fmt", "lint")
