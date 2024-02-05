# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from pathlib import Path

from pants.backend.terraform.dependencies import TerraformInitRequest, TerraformInitResponse
from pants.backend.terraform.goals.lockfiles import GenerateTerraformLockfile
from pants.backend.terraform.target_types import (
    TerraformDependenciesField,
    TerraformRootModuleField,
)
from pants.core.goals.export import ExportResult, ExportResults, PostProcessingCommand
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule


@rule
async def export_terraform(
    lockfile_request: GenerateTerraformLockfile,
) -> ExportResults:
    print(f"{lockfile_request.target=}")

    initialised_terraform = await Get(
        TerraformInitResponse,
        TerraformInitRequest(
            TerraformRootModuleField(
                lockfile_request.target.address.spec, lockfile_request.target.address
            ),
            lockfile_request.target[TerraformDependenciesField],
            initialise_backend=True,
            upgrade=False,
        ),
    )
    export_dest = (Path(initialised_terraform.chdir) / ".terraform").as_posix()

    return ExportResults(
        (
            ExportResult(
                f"export Terraform for {lockfile_request.resolve_name}",
                export_dest,
                digest=initialised_terraform.third_party_deps,
                resolve=lockfile_request.resolve_name,
                post_processing_cmds=[
                    PostProcessingCommand(
                        ["ln", "-s", os.path.join("{digest_root}", export_dest), export_dest]
                    )
                ],
            ),
        )
    )


def rules():
    return (*collect_rules(),)
