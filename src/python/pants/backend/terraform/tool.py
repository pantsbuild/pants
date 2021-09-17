# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.fs import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel
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


@dataclass(frozen=True)
class TerraformProcess:
    """A request to invoke Terraform."""

    args: tuple[str, ...]
    description: str
    input_digest: Digest = EMPTY_DIGEST
    output_files: tuple[str, ...] = ()


@rule
async def setup_terraform_process(request: TerraformProcess, terraform: TerraformTool) -> Process:
    downloaded_terraform = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        terraform.get_request(Platform.current),
    )

    input_digest = await Get(
        Digest,
        MergeDigests((request.input_digest, downloaded_terraform.digest)),
    )

    return Process(
        argv=("./terraform",) + request.args,
        input_digest=input_digest,
        output_files=request.output_files,
        description=request.description,
        level=LogLevel.DEBUG,
    )


def rules():
    return collect_rules()
