# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Tuple

from pants.backend.python.helpers.metalint import MetalintTool, make_linter
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.option.option_types import ArgsListOption


def rules():
    class RadonTool(MetalintTool):
        options_scope = "radon"
        name = "radon"
        help = """Radon is a Python tool which computes various code metrics."""

        default_version = "radon==5.1.0"
        default_main = ConsoleScript("radon")

        args = ArgsListOption(example="--no-assert")

        def config_request(self) -> ConfigFilesRequest:
            """https://radon.readthedocs.io/en/latest/commandline.html#radon-configuration-files."""
            return ConfigFilesRequest(
                specified=self.config,
                specified_option_name=f"[{self.options_scope}].config",
                discovery=self.config_discovery,
                check_existence=["radon.cfg"],
                check_content={"setup.cfg": b"[radon]"},
            )

    def radon_cc_args(tool: MetalintTool, files: Tuple[str, ...]):
        return ["cc"] + ["-s", "--total-average", "--no-assert", "-nb"] + list(files)

    radoncc = make_linter(RadonTool, "radoncc", radon_cc_args)

    def radon_mi_args(tool: MetalintTool, files: Tuple[str, ...]):
        return ["mi"] + ["-m", "-s"] + list(files)

    radonmi = make_linter(RadonTool, "radonmi", radon_mi_args)

    class VultureTool(MetalintTool):
        options_scope = "vulture"
        name = "Vulture"
        help = """Vulture finds unused code in Python programs"""

        default_version = "vulture==2.5"
        default_main = ConsoleScript("vulture")

        args = ArgsListOption(example="--min-confidence 95")

    def vulture_args(tool: VultureTool, files: Tuple[str, ...]):
        return tool.args + files

    vulture = make_linter(VultureTool, "vulture", vulture_args)

    return [
        *radoncc.rules(),
        *radonmi.rules(),
        *vulture.rules(),
    ]
