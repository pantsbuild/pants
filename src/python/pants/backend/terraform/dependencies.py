# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pants.backend.terraform.target_types import (
    TerraformBackendConfigField,
    TerraformDependenciesField,
    TerraformRootModuleField,
)
from pants.backend.terraform.tool import TerraformProcess
from pants.backend.terraform.utils import terraform_arg, terraform_relpath
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, MergeDigests, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import SourcesField, TransitiveTargets, TransitiveTargetsRequest


@dataclass(frozen=True)
class TerraformDependenciesRequest:
    chdir: str
    backend_config: SourceFiles
    lockfile: Snapshot
    dependencies_files: SourceFiles

    # Not initialising the backend means we won't access remote state. Useful for `validate`
    initialise_backend: bool = False


@dataclass(frozen=True)
class TerraformDependenciesResponse:
    digest: Digest


@rule
async def get_terraform_providers(
    req: TerraformDependenciesRequest,
) -> TerraformDependenciesResponse:
    args = ["init"]
    if req.backend_config.files:
        args.append(
            terraform_arg(
                "-backend-config",
                terraform_relpath(req.chdir, req.backend_config.files[0]),
            )
        )
        backend_digest = req.backend_config.snapshot.digest
    else:
        backend_digest = EMPTY_DIGEST

    args.append(terraform_arg("-backend", str(req.initialise_backend)))

    # If we have a lockfile, don't modify it
    if req.lockfile.files:
        args.append("-lockfile=readonly")

    with_backend_config = await Get(
        Digest,
        MergeDigests(
            [
                backend_digest,
                req.lockfile.digest,
                req.dependencies_files.snapshot.digest,
            ]
        ),
    )

    fetched_deps = await Get(
        FallibleProcessResult,
        TerraformProcess(
            args=tuple(args),
            input_digest=with_backend_config,
            output_files=(".terraform.lock.hcl",),
            output_directories=(".terraform",),
            description="Run `terraform init` to fetch dependencies",
            chdir=req.chdir,
        ),
    )

    return TerraformDependenciesResponse(fetched_deps.output_digest)


@dataclass(frozen=True)
class TerraformInitRequest:
    root_module: TerraformRootModuleField
    backend_config: TerraformBackendConfigField
    dependencies: TerraformDependenciesField

    # Not initialising the backend means we won't access remote state. Useful for `validate`
    initialise_backend: bool = False


@dataclass(frozen=True)
class TerraformInitResponse:
    terraform_dependencies: Digest
    terraform_files: SourceFiles
    sources_and_deps: Digest
    chdir: str


@rule
async def init_terraform(request: TerraformInitRequest) -> TerraformInitResponse:
    module_dependencies = await Get(
        TransitiveTargets, TransitiveTargetsRequest((request.dependencies.address,))
    )

    backend_config, lockfile, dependencies_files = await MultiGet(
        Get(SourceFiles, SourceFilesRequest([request.backend_config])),
        Get(
            Snapshot,
            PathGlobs(
                [(Path(request.root_module.address.spec_path) / ".terraform.lock.hcl").as_posix()]
            ),
        ),
        Get(
            SourceFiles,
            SourceFilesRequest([tgt.get(SourcesField) for tgt in module_dependencies.dependencies]),
        ),
    )
    fetched_deps = await Get(
        TerraformDependenciesResponse,
        TerraformDependenciesRequest(
            request.root_module.address.spec_path,
            backend_config,
            lockfile,
            dependencies_files,
            initialise_backend=request.initialise_backend,
        ),
    )

    all_terraform_files = await Get(
        Digest, MergeDigests([fetched_deps.digest, dependencies_files.snapshot.digest])
    )

    return TerraformInitResponse(
        terraform_dependencies=fetched_deps.digest,
        terraform_files=dependencies_files,  # TODO: I think this includes the wrong files (all the dependencies, not just TF ones). It's now a bit muddled which files are actually TF files
        sources_and_deps=all_terraform_files,
        chdir=request.root_module.address.spec_path,
    )


def rules():
    return collect_rules()
