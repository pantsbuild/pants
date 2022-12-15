# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.option.option_types import ArgsListOption, FileOption, SkipOption
from pants.util.strutil import softwrap


class Yamllint(PythonToolBase):
    name = "Yamllint"
    options_scope = "yamllint"
    help = "A linter for YAML files (https://yamllint.readthedocs.io)"

    default_version = "yamllint==1.28.0"
    default_main = ConsoleScript("yamllint")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6,<4"]

    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            """
            Path to a config file understood by yamllint
            (https://yamllint.readthedocs.io/en/stable/configuration.html).
            """
        ),
    )

    args = ArgsListOption(example="-d relaxed")

    skip = SkipOption("lint")

    def config_request(self) -> ConfigFilesRequest:
        candidates = [
            ".yamllint",
            ".yamllint.yaml",
            ".yamllint.yml",
        ]
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=True,
            check_existence=candidates,
        )
