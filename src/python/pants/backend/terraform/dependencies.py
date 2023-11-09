# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pants.backend.terraform.target_types import (
    TerraformBackendTargetField,
    TerraformDependenciesField,
    TerraformRootModuleField,
    to_address_input,
)
from pants.backend.terraform.tool import TerraformProcess
from pants.backend.terraform.utils import terraform_arg, terraform_relpath
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import (
    EMPTY_DIGEST,
    EMPTY_SNAPSHOT,
    Address,
    AddressInput,
    Digest,
    MergeDigests,
    Snapshot,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    SourcesField,
    TransitiveTargets,
    TransitiveTargetsRequest,
    WrappedTarget,
    WrappedTargetRequest,
)


@dataclass(frozen=True)
class TerraformDependenciesRequest:
    chdir: str
    backend_config: SourceFiles
    lockfile: Snapshot
    dependencies_files: SourceFiles

    # Not initialising the backend means we won't access remote state. Useful for `validate`
    initialise_backend: bool = False
    # Upgrade the dependencies, necessary for upgrading the lockfile
    upgrade: bool = False


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

    # If we have a lockfile and aren't regenerating it, don't modify it
    if req.lockfile.files and not req.upgrade:
        args.append("-lockfile=readonly")

    if req.upgrade:
        args.append("-upgrade")

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
    backend_config: TerraformBackendTargetField
    dependencies: TerraformDependenciesField

    # Not initialising the backend means we won't access remote state. Useful for `validate`
    initialise_backend: bool = False
    upgrade: bool = False


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

    if request.backend_config.value:
        backend_address = await Get(Address, AddressInput, to_address_input(request.backend_config))
        backend_target = await Get(
            WrappedTarget,
            WrappedTargetRequest(backend_address, description_of_origin="Terraform initialisation"),
        )
        backend_sources = await Get(
            SourceFiles, SourceFilesRequest([backend_target.target.get(SourcesField)])
        )
    else:
        backend_sources = SourceFiles(EMPTY_SNAPSHOT, ())

    lockfile, dependencies_files = await MultiGet(
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
            backend_sources,
            lockfile,
            dependencies_files,
            initialise_backend=request.initialise_backend,
            upgrade=request.upgrade,
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
