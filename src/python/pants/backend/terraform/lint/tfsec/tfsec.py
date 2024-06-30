# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from dataclasses import dataclass

from pants.backend.terraform.target_types import TerraformFieldSet
from pants.base.deprecated import deprecated_conditional
from pants.core.goals.lint import LintTargetsRequest
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import ExternalTool
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.platform import Platform
from pants.engine.target import BoolField, Target
from pants.option.option_types import ArgsListOption, BoolOption, DirOption, FileOption, SkipOption
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class TFSec(ExternalTool):
    """Static analysis of Terraform, by Aqua Security."""

    options_scope = "terraform-tfsec"
    name = "tfsec"
    help = "tfsec by Aqua Security"
    default_version = "1.28.6"
    default_known_versions = [
        "1.28.6|linux_x86_64|8cbd8d64cbd1f25b38f33fa04db602466dade79e99c99dc9da053b5962d34014|30175259",
        "1.28.6|linux_arm64|4bc7b0f0592be4fa384cff52af5b1cdd2066ba7a06001bea98690340851c0bce|27577217",
        "1.28.6|macos_x86_64|3b31e954819faa7d6151b999548cefb782f2f4dc64b355c8747e44d4b0b2faca|31168281",
        "1.28.6|macos_arm64|aa132b7e0e69e16f1c9320257841751e52c42d9791b7f900de72cf0b06ffe74c|30083056",
        "1.28.1|linux_x86_64|57b902b31da3eed12448a4e82a8aca30477e4bcd1bf99e3f65310eae0889f88d|26427634",
        "1.28.1|linux_arm64 |20daad803d2a7a781f2ef0ee72ba4ed4ae17dcb41a43a330ae7b98347762bec9|24299157",
        "1.28.1|macos_x86_64|6d9f5a747b1fcc1b6c314d30f4ff4d753371e5690309a99a5dd653d719d20d2d|27293876",
        "1.28.1|macos_arm64 |6d664dcdd37e2809d1b4f14b310ccda0973b4a29e4624e902286e4964d101e22|26478632",
    ]

    skip = SkipOption("lint")
    args = ArgsListOption(example="--minimum-severity=MEDIUM")
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            """
            Path to the tfsec config file (https://aquasecurity.github.io/tfsec/latest/guides/configuration/config/)

            Setting this option will disable config discovery for the config file. Use this option if the config is located in a non-standard location.
            """
        ),
    )
    custom_check_dir = DirOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            """
            Path to the directory containing custom checks (https://aquasecurity.github.io/tfsec/latest/guides/configuration/custom-checks/#overriding-check-directory)

            Setting this option will disable config discovery for custom checks. Use this option if the custom checks dir is located in a non-standard location.
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

            Use `[{cls.options_scope}].config` and `[{cls.options_scope}].custom_check_dir` instead if your config is in a non-standard location.
            """
        ),
    )

    def config_request(self) -> ConfigFilesRequest:
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[".tfsec/config.json", ".tfsec/config.yml", ".tfsec/config.yaml"],
        )

    def custom_checks_request(self) -> ConfigFilesRequest:
        return ConfigFilesRequest(
            specified=self.custom_check_dir,
            specified_option_name=f"[{self.options_scope}].custom_check_dir",
            discovery=self.config_discovery,
            check_existence=[".tfsec/*.json", ".tfsec/*.yml", ".tfsec/*.yaml"],
        )

    def generate_url(self, plat: Platform) -> str:
        deprecated_conditional(
            lambda: self.version.startswith("v"),
            removal_version="2.26.0.dev0",
            entity="using a version beginning with 'v'",
            hint=f"Remove the leading 'v' from `[{self.options_scope}].version` and from versions in `[{self.options_scope}].known_versions`",
        )

        plat_str = {
            "macos_arm64": "darwin_arm64",
            "macos_x86_64": "darwin_amd64",
            "linux_arm64": "linux_arm64",
            "linux_x86_64": "linux_amd64",
        }[plat.value]

        # backwards compatibility with version strings beginning with 'v'
        version = self.version
        if version.startswith("v"):
            version = version[1:]

        return f"https://github.com/aquasecurity/tfsec/releases/download/v{version}/tfsec_{version}_{plat_str}.tar.gz"

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
