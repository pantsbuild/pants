# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum
from typing import cast

from pants.backend.helm.util_rules.plugins import HelmPluginSubsystem
from pants.engine.platform import Platform


class HelmUnitTestReportFormat(Enum):
    """The report format used for the unit tests."""

    XUNIT = "XUnit"
    NUNIT = "NUnit"
    JUNIT = "JUnit"


class HelmUnitTestPlugin(HelmPluginSubsystem):
    options_scope = "helm-unittest"
    plugin_name = "unittest"
    help = "BDD styled unit test framework for Kubernetes Helm charts as a Helm plugin."

    default_version = "0.2.8"
    default_known_versions = [
        "0.2.8|linux_x86_64|d7c452559ad4406a1197435394fbcffe51198060de1aa9b4cb6feaf876776ba0|18299096",
        "0.2.8|linux_arm64 |c793e241b063f0540ad9b4acc0a02e5a101bd9daea5bdf4d8562e9b2337fedb2|16943867",
        "0.2.8|macos_x86_64|1dc95699320894bdebf055c4f4cc084c2cfa0133d3cb7fd6a4c0adca94df5c96|18161928",
        "0.2.8|macos_arm64 |436e3167c26f71258b96e32c2877b4f97c051064db941de097cf3db2fc861342|17621648",
    ]
    default_url_template = "https://github.com/quintush/helm-unittest/releases/download/v{version}/helm-unittest-{platform}-{version}.tgz"
    default_url_platform_mapping = {
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-amd64",
        "macos_arm64": "macos-arm64",
        "macos_x86_64": "macos-amd64",
    }

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--output-type",
            type=HelmUnitTestReportFormat,
            default=HelmUnitTestReportFormat.XUNIT,
            help="Output type used for the test report",
        )

    def generate_exe(self, _: Platform) -> str:
        return "./untt"

    @property
    def output_type(self) -> HelmUnitTestReportFormat:
        return cast(HelmUnitTestReportFormat, self.options.output_type)
