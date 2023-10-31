# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from dataclasses import dataclass

from pants.backend.terraform.target_types import TerraformFieldSet
from pants.core.goals.lint import LintTargetsRequest
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import ExternalTool
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.platform import Platform
from pants.engine.target import BoolField, Target
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class TFSec(ExternalTool):
    """Static analysis of Terraform, by Aqua Security."""

    options_scope = "terraform-tfsec"
    name = "tfsec"
    help = "tfsec by Aqua Security"
    default_version = "v1.28.1"
    default_known_versions = [
        "v1.28.1|linux_x86_64|57b902b31da3eed12448a4e82a8aca30477e4bcd1bf99e3f65310eae0889f88d|26427634"
    ]

    skip = SkipOption("lint")
    args = ArgsListOption(example="--minimum-severity=MEDIUM")
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to the tfsec config file (https://aquasecurity.github.io/tfsec/latest/guides/configuration/config/)

            Setting this option will disable `[{cls.options_scope}].config_discovery`. Use this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include all relevant config files during runs (`.tfsec/config.json` or `.tfsec/config.yml`).
            Note that you will have to tell Pants to include this file by adding `"!.tfsec/"` to `[global].pants_ignore.add`.

            Use `[{cls.options_scope}].config` instead if your config is in a non-standard location.
            """
        ),
    )

    def config_request(self) -> ConfigFilesRequest:
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[".tfsec/config.json", ".tfsec/config.yml"],
        )

    def generate_url(self, plat: Platform) -> str:
        plat_str = {
            "macos_arm64": "darwin_arm64",
            "macos_x86_64": "darwin_amd64",
            "linux_arm64": "linux_arm64",
            "linux_x86_64": "linux_amd64",
        }[plat.value]
        return f"https://github.com/aquasecurity/tfsec/releases/download/{self.version}/tfsec_{self.version[1:]}_{plat_str}.tar.gz"

    def generate_exe(self, _: Platform) -> str:
        return "./tfsec"


class SkipTfSecField(BoolField):
    alias = "skip_tfsec"
    default = False
    help = "If true, don't run tfsec on this target's Terraform files."


@dataclass(frozen=True)
class TfSecFieldSet(TerraformFieldSet):
    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipTfSecField).value


class TfSecRequest(LintTargetsRequest):
    field_set_type = TfSecFieldSet
    tool_subsystem = TFSec
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION
