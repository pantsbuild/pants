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
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.meta import classproperty


class TerraformTool(TemplatedExternalTool):
    options_scope = "download-terraform"
    name = "terraform"
    help = "Terraform (https://terraform.io)"

    default_version = "1.0.7"
    default_url_template = (
        "https://releases.hashicorp.com/terraform/{version}/terraform_{version}_{platform}.zip"
    )
    default_url_platform_mapping = {
        "macos_arm64": "darwin_arm64",
        "macos_x86_64": "darwin_amd64",
        "linux_x86_64": "linux_amd64",
    }

    @classproperty
    def default_known_versions(cls):
        return [
            "1.0.7|macos_arm64 |cbab9aca5bc4e604565697355eed185bb699733811374761b92000cc188a7725|32071346",
            "1.0.7|macos_x86_64|80ae021d6143c7f7cbf4571f65595d154561a2a25fd934b7a8ccc1ebf3014b9b|33020029",
            "1.0.7|linux_x86_64|bc79e47649e2529049a356f9e60e06b47462bf6743534a10a4c16594f443be7b|32671441",
        ]


class TerraformSubsystem(Subsystem):
    options_scope = "terraform"
    help = "Terraform-relaed options"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--path",
            type=str,
            default=None,
            help=(
                "Use this provided absolute path as the path to the `terraform` binary. "
                "Prevents the automatic download of Terraform.",
            ),
        )


@dataclass(frozen=True)
class TerraformSetup:
    digest: Digest
    path: str


@rule
async def find_terraform(
    tf_tool: TerraformTool, tf_subsystem: TerraformSubsystem
) -> TerraformSetup:
    if tf_subsystem.options.path:
        return TerraformSetup(digest=EMPTY_DIGEST, path=tf_subsystem.options.path)

    downloaded_terraform = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        tf_tool.get_request(Platform.current),
    )

    return TerraformSetup(digest=downloaded_terraform.digest, path="./terraform")


@dataclass(frozen=True)
class TerraformProcess:
    """A request to invoke Terraform."""

    args: tuple[str, ...]
    description: str
    input_digest: Digest = EMPTY_DIGEST
    output_files: tuple[str, ...] = ()


@rule
async def setup_terraform_process(
    request: TerraformProcess, terraform_setup: TerraformSetup
) -> Process:
    input_digest = await Get(
        Digest,
        MergeDigests((request.input_digest, terraform_setup.digest)),
    )

    return Process(
        argv=(terraform_setup.path,) + request.args,
        input_digest=input_digest,
        output_files=request.output_files,
        description=request.description,
        level=LogLevel.DEBUG,
    )


def rules():
    return collect_rules()
