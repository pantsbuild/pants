# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from dataclasses import dataclass

from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
    Process,
)
from pants.engine.rules import collect_rules, rule
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.ordered_set import OrderedSet


class TerraformTool(TemplatedExternalTool):
    options_scope = "terraform"
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

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--path",
            type=str,
            default=None,
            help=(
                "Use the provided absolute path as the path to the `terraform` binary. "
                "Prevents the automatic download of Terraform and search of paths.",
            ),
        )

        register(
            "--search-paths",
            type=list,
            member_type=str,
            default=[],
            help=(
                "A list of paths to search for Terraform.\n\n"
                "Specify absolute paths to directories with the `terraform` binary, e.g. `/usr/bin`. "
                "Earlier entries will be searched first.\n\n"
                "The special string '<PATH>' will expand to the contents of the PATH env var."
            ),
        )

    def search_paths(self, env: Environment) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self.options.search_paths:
                if entry == "<PATH>":
                    path = env.get("PATH")
                    if path:
                        for path_entry in path.split(os.pathsep):
                            yield path_entry
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))


@dataclass(frozen=True)
class TerraformSetup:
    digest: Digest
    path: str


@rule
async def find_terraform(terraform: TerraformTool) -> TerraformSetup:
    if terraform.options.path:
        return TerraformSetup(digest=EMPTY_DIGEST, path=terraform.options.path)

    env = await Get(Environment, EnvironmentRequest(["PATH"]))
    search_paths = terraform.search_paths(env)
    if search_paths:
        all_terraform_binary_paths = await Get(
            BinaryPaths,
            BinaryPathRequest(
                search_path=search_paths,
                binary_name="terraform",
                test=BinaryPathTest(["version"]),
            ),
        )

        if not all_terraform_binary_paths.paths:
            raise BinaryNotFoundError(
                "Cannot find any `terraform` binaries using the option "
                f"`[terraform].search_paths`: {list(search_paths)}\n\n"
                "To fix, please install one copy of Terraform and ensure "
                "that it is discoverable via `[terraform].search_paths`."
            )

        if len(all_terraform_binary_paths.paths) > 1:
            raise BinaryNotFoundError(
                "Found multiple `terraform` binaries using the option "
                f"`[terraform].search_paths`: {list(search_paths)}\n\n"
                "To fix, please ensure that only one copy of Terraform "
                "is discoverable via `[terraform].search_paths`."
            )

        return TerraformSetup(digest=EMPTY_DIGEST, path=all_terraform_binary_paths.paths[0])

    downloaded_terraform = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        terraform.get_request(Platform.current),
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
