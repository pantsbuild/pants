# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum

from pants.backend.helm.util_rules.tool import (
    ExternalHelmPlugin,
    ExternalHelmPluginBinding,
    ExternalHelmPluginRequest,
)
from pants.core.goals.resolves import ExportableTool
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

    default_version = "1.0.1"
    default_known_versions = [
        "1.0.1|linux_arm64 |68e8ec894408bfd5a53de6299248cb438555a42b4cae1463a3fe4a4240dcbcd4|23979610",
        "1.0.1|linux_x86_64|7e99822df43aaf25e198d0b5c950c1d31d1c5baa528adee8fa9b4063a761aced|26056496",
        "1.0.1|macos_arm64 |92c5f3bcef1b75337d07ba05d48b40ec2190bc8a4fb4ba05e93664f93e28afa0|24374980",
        "1.0.1|macos_x86_64|3d6e88fce7d177025c47e840d804d1ef195c2fb07581797be477b002901f32d9|25991137",
        "0.8.0|linux_arm64 |ca8be393510f4afad9ec64a6ba2666aae6333bd92169b249533aeaba440a61ec|22473391",
        "0.8.0|linux_x86_64|3f436992adcc59a5e640d3d2889ccb275f22ad7cde8c8b8354b24728f4dd6f99|24293223",
        "0.8.0|macos_arm64 |8275958346cc934c19b06bfc76f4a837ec7ab4c38f8cf8e980b7b93aa6b4d838|22776975",
        "0.8.0|macos_x86_64|4dfe519a0f0172e179f5a624f0a5fb20c3fa12737b182a1e244fda87e2dc2a7a|24199798",
        "0.3.3|linux_arm64 |7f5e4426428cb9678f971576103df410e6fa38dd19b87fce4729f5217bd5c683|19944514",
        "0.3.3|linux_x86_64|8ebe20f77012a5d4e7139760cabe36dd1ea38e40b26f57de3f4165d96bd486ff|21685365",
        "0.3.3|macos_arm64 |2365f5b3a99e6fc83218457046378b14039a3992e9ae96a4192bc2e43a33c742|20479438",
        "0.3.3|macos_x86_64|b2298a513b3cb6482ba2e42079c93ad18be8a31a230bd4dffdeb01ec2881d0f5|21497144",
        "0.2.8|linux_arm64 |c793e241b063f0540ad9b4acc0a02e5a101bd9daea5bdf4d8562e9b2337fedb2|16943867",
        "0.2.8|linux_x86_64|d7c452559ad4406a1197435394fbcffe51198060de1aa9b4cb6feaf876776ba0|18299096",
        "0.2.8|macos_arm64 |436e3167c26f71258b96e32c2877b4f97c051064db941de097cf3db2fc861342|17621648",
        "0.2.8|macos_x86_64|1dc95699320894bdebf055c4f4cc084c2cfa0133d3cb7fd6a4c0adca94df5c96|18161928",
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
async def download_unittest_plugin_request(
    _: HelmUnitTestPluginBinding, subsystem: HelmUnitTestSubsystem, platform: Platform
) -> ExternalHelmPluginRequest:
    return ExternalHelmPluginRequest.from_subsystem(subsystem, platform)


def rules():
    return [
        *collect_rules(),
        UnionRule(ExternalHelmPluginBinding, HelmUnitTestPluginBinding),
        UnionRule(ExportableTool, HelmUnitTestSubsystem),
    ]
