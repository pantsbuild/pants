# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
    def default_known_versions(cls):
        return [
            "0.14.5|macos_arm64 |363d0e0c5c4cb4e69f5f2c7f64f9bf01ab73af0801665d577441521a24313a07|34341379",
            "0.14.5|macos_x86_64|363d0e0c5c4cb4e69f5f2c7f64f9bf01ab73af0801665d577441521a24313a07|34341379",
            "0.14.5|linux_x86_64|2899f47860b7752e31872e4d57b1c03c99de154f12f0fc84965e231bc50f312f|33542124",
        ]


def rules():
    return collect_rules()
