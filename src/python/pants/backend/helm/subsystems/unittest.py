# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum

from pants.backend.helm.util_rules.tool import (
    ExternalHelmPlugin,
    ExternalHelmPluginBinding,
    ExternalHelmPluginRequest,
)
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption, EnumOption, SkipOption


class HelmUnitTestReportFormat(Enum):
    """The report format used for the unit tests."""

    XUNIT = "XUnit"
    NUNIT = "NUnit"
    JUNIT = "JUnit"


class HelmUnitTestSubsystem(ExternalHelmPlugin):
    options_scope = "helm-unittest"
    plugin_name = "unittest"
    help = "BDD styled unit test framework for Kubernetes Helm charts as a Helm plugin. (https://github.com/helm-unittest)"

    default_version = "0.3.3"
    default_known_versions = [
        "0.3.3|linux_x86_64|8ebe20f77012a5d4e7139760cabe36dd1ea38e40b26f57de3f4165d96bd486ff|21685365",
        "0.3.3|linux_arm64 |7f5e4426428cb9678f971576103df410e6fa38dd19b87fce4729f5217bd5c683|19944514",
        "0.3.3|macos_x86_64|b2298a513b3cb6482ba2e42079c93ad18be8a31a230bd4dffdeb01ec2881d0f5|21497144",
        "0.3.3|macos_arm64 |2365f5b3a99e6fc83218457046378b14039a3992e9ae96a4192bc2e43a33c742|20479438",
        "0.2.8|linux_x86_64|d7c452559ad4406a1197435394fbcffe51198060de1aa9b4cb6feaf876776ba0|18299096",
        "0.2.8|linux_arm64 |c793e241b063f0540ad9b4acc0a02e5a101bd9daea5bdf4d8562e9b2337fedb2|16943867",
        "0.2.8|macos_x86_64|1dc95699320894bdebf055c4f4cc084c2cfa0133d3cb7fd6a4c0adca94df5c96|18161928",
        "0.2.8|macos_arm64 |436e3167c26f71258b96e32c2877b4f97c051064db941de097cf3db2fc861342|17621648",
    ]
    default_url_template = "https://github.com/helm-unittest/helm-unittest/releases/download/v{version}/helm-unittest-{platform}-{version}.tgz"
    default_url_platform_mapping = {
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-amd64",
        "macos_arm64": "macos-arm64",
        "macos_x86_64": "macos-amd64",
    }

    color = BoolOption(
        "--color",
        default=False,
        help="Enforce printing colored output even if stdout is not a tty.",
    )

    output_type = EnumOption(
        default=HelmUnitTestReportFormat.XUNIT,
        help="Output type used for the test report.",
    )

    skip = SkipOption("test")

    def generate_exe(self, _: Platform) -> str:
        return "./untt"


class HelmUnitTestPluginBinding(ExternalHelmPluginBinding[HelmUnitTestSubsystem]):
    plugin_subsystem_cls = HelmUnitTestSubsystem


@rule
def download_unittest_plugin_request(
    _: HelmUnitTestPluginBinding, subsystem: HelmUnitTestSubsystem, platform: Platform
) -> ExternalHelmPluginRequest:
    return ExternalHelmPluginRequest.from_subsystem(subsystem, platform)


def rules():
    return [
        *collect_rules(),
        UnionRule(ExternalHelmPluginBinding, HelmUnitTestPluginBinding),
    ]
