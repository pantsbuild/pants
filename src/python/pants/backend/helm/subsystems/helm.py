# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import BoolOption


class HelmSubsystem(TemplatedExternalTool):
    options_scope = "helm"
    help = "The Helm command line (https://helm.sh)"

    default_version = "3.8.0"
    default_known_versions = [
        "3.8.0|linux_arm64 |23e08035dc0106fe4e0bd85800fd795b2b9ecd9f32187aa16c49b0a917105161|12324642",
        "3.8.0|linux_x86_64|8408c91e846c5b9ba15eb6b1a5a79fc22dd4d33ac6ea63388e5698d1b2320c8b|13626774",
        "3.8.0|macos_arm64 |751348f1a4a876ffe089fd68df6aea310fd05fe3b163ab76aa62632e327122f3|14078604",
        "3.8.0|macos_x86_64|532ddd6213891084873e5c2dcafa577f425ca662a6594a3389e288fc48dc2089|14318316",
    ]
    default_url_template = "https://get.helm.sh/helm-v{version}-{platform}.tar.gz"
    default_url_platform_mapping = {
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-amd64",
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-amd64",
    }

    lint_strict = BoolOption(
        "--lint-strict", default=False, help="Enables strict linting of Helm charts"
    )

    def generate_exe(self, plat: Platform) -> str:
        mapped_plat = self.default_url_platform_mapping[plat.value]
        bin_path = os.path.join(mapped_plat, "helm")
        return bin_path
