# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.rules import collect_rules
from pants.util.meta import classproperty


class TerraformTool(TemplatedExternalTool):
    options_scope = "download-terraform"
    name = "terraform"
    help = "Terraform (https://terraform.io)"

    default_version = "0.14.5"
    default_url_template = (
        "https://releases.hashicorp.com/terraform/{version}/terraform_{version}_{platform}.zip"
    )
    default_url_platform_mapping = {
        "macos_arm64": "darwin_amd64",
        "macos_x86_64": "darwin_amd64",
        "linux_x86_64": "linux_amd64",
    }

    @classproperty
    def default_known_versions(cls) -> list[str]:
        return [
            "0.14.5|macos_arm64 |363d0e0c5c4cb4e69f5f2c7f64f9bf01ab73af0801665d577441521a24313a07|34341379",
            "0.14.5|macos_x86_64|363d0e0c5c4cb4e69f5f2c7f64f9bf01ab73af0801665d577441521a24313a07|34341379",
            "0.14.5|linux_x86_64|2899f47860b7752e31872e4d57b1c03c99de154f12f0fc84965e231bc50f312f|33542124",
            "1.0.5|macos_arm64|3de4b9f167392622ef49d807e438a166e6c86c631afa730ff3189cf72cc950e2|31803011",
            "1.0.5|macos_x86_64|ae0b07ba099d3d9241e5e8bcdfc88ada8fcbbe302cb1d8f822da866a25e55330|32751135",
            "1.0.5|linux_x86_64|7ce24478859ab7ca0ba4d8c9c12bb345f52e8efdc42fa3ef9dd30033dbf4b561|32416786",
            "1.0.6|macos_arm64|aaff1eccaf4099da22fe3c6b662011f8295dad9c94a35e1557b92844610f91f3|32080428",
            "1.0.6|macos_x86_64|3a97f2fffb75ac47a320d1595e20947afc8324571a784f1bd50bd91e26d5648c|33022053",
            "1.0.6|linux_x86_64|6a454323d252d34e928785a3b7c52bfaff1192f82685dfee4da1279bb700b733|32677516",
        ]


def rules():
    return collect_rules()
