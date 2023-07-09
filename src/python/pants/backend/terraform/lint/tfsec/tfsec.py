# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from dataclasses import dataclass

from pants.backend.terraform.target_types import TerraformFieldSet
from pants.core.goals.lint import LintTargetsRequest
from pants.core.util_rules.external_tool import ExternalTool
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.platform import Platform
from pants.option.option_types import SkipOption

logger = logging.getLogger(__name__)


class TfSec(ExternalTool):
    """Static analysis of Terraform, by Aqua Security."""

    options_scope = "terraform-tfsec"
    name = "tfsec"
    help = "TFSec by Aqua Security"
    default_version = "v1.28.1"
    default_known_versions = [
        "v1.28.1|linux_x86_64|57b902b31da3eed12448a4e82a8aca30477e4bcd1bf99e3f65310eae0889f88d|26427634"
    ]

    skip = SkipOption("lint")

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


@dataclass(frozen=True)
class TfSecFieldSet(TerraformFieldSet):
    ...


class TfSecRequest(LintTargetsRequest):
    field_set_type = TfSecFieldSet
    tool_subsystem = TfSec
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION
