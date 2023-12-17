# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.terraform.dependency_inference import find_targets_of_type
from pants.backend.terraform.partition import partition_files_by_directory
from pants.backend.terraform.target_types import (
    TerraformBackendTarget,
    TerraformDependenciesField,
    TerraformRootModuleField,
)
from pants.backend.terraform.tool import TerraformProcess
from pants.backend.terraform.utils import terraform_arg, terraform_relpath
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.native_engine import Address, AddressInput, Digest, MergeDigests
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
    source_files: SourceFiles
    directories: Tuple[str, ...]
    backend_config: Optional[str]
    dependencies_files: SourceFiles

    # Not initialising the backend means we won't access remote state. Useful for `validate`
    initialise_backend: bool = False


@dataclass(frozen=True)
class TerraformDependenciesResponse:
    fetched_deps: Tuple[Tuple[str, Digest], ...]


@rule
async def get_terraform_providers(
    req: TerraformDependenciesRequest,
) -> TerraformDependenciesResponse:
    args = ["init"]
    if req.backend_config:
        args.append(
            terraform_arg(
                "-backend-config",
                terraform_relpath(req.directories[0], req.backend_config),
            )
        )

    args.append(terraform_arg("-backend", str(req.initialise_backend)))

    with_backend_config = await Get(
        Digest,
        MergeDigests(
            [
                req.source_files.snapshot.digest,
                req.dependencies_files.snapshot.digest,
            ]
        ),
    )

    # TODO: Does this need to be a MultiGet? I think we will now always get one directory
    fetched_deps = await MultiGet(
        Get(
            FallibleProcessResult,
            TerraformProcess(
                args=tuple(args),
                input_digest=with_backend_config,
                output_files=(".terraform.lock.hcl",),
                output_directories=(".terraform",),
                description="Run `terraform init` to fetch dependencies",
                chdir=directory,
            ),
        )
        for directory in req.directories
    )

    return TerraformDependenciesResponse(
        tuple(zip(req.directories, (x.output_digest for x in fetched_deps)))
    )


@dataclass(frozen=True)
class TerraformInitRequest:
    root_module: TerraformRootModuleField
    dependencies: TerraformDependenciesField

    # Not initialising the backend means we won't access remote state. Useful for `validate`
    initialise_backend: bool = False


@dataclass(frozen=True)
class TerraformInitResponse:
    sources_and_deps: Digest
    terraform_files: tuple[str, ...]
    chdir: str


@rule
async def init_terraform(request: TerraformInitRequest) -> TerraformInitResponse:
    module_dependencies = await Get(
        TransitiveTargets, TransitiveTargetsRequest((request.dependencies.address,))
    )

    # TODO: is this still necessary, or do we pull it in with (transitive) depenendencies?
    address_input = request.root_module.to_address_input()
    module_address = await Get(Address, AddressInput, address_input)
    module = await Get(
        WrappedTarget,
        WrappedTargetRequest(
            module_address, description_of_origin=address_input.description_of_origin
        ),
    )

    source_files, dependencies_files = await MultiGet(
        Get(SourceFiles, SourceFilesRequest([module.target.get(SourcesField)])),
        Get(
            SourceFiles,
            SourceFilesRequest([tgt.get(SourcesField) for tgt in module_dependencies.dependencies]),
        ),
    )
    files_by_directory = partition_files_by_directory(source_files.files)

    backend_config_tgts = find_targets_of_type(
        module_dependencies.dependencies, TerraformBackendTarget
    )
    # TODO: maybe we should identify this earlier?
    #  if we did at dependency inference,
    #  we could include only the inferred one directly
    #  and not involve transitive dependencies
    if len(backend_config_tgts) == 0:
        backend_config = None
    elif len(backend_config_tgts) == 1:
        backend_config_sources = await Get(
            SourceFiles, SourceFilesRequest([backend_config_tgts[0].get(SourcesField)])
        )
        backend_config = backend_config_sources.snapshot.files[0]
    else:
        backend_config_names = [e.address for e in backend_config_tgts]
        raise ValueError(
            f"Found more than 1 backend config for a Terraform deployment. identified {backend_config_names}"
        )

    fetched_deps = await Get(
        TerraformDependenciesResponse,
        TerraformDependenciesRequest(
            source_files,
            tuple(files_by_directory.keys()),
            backend_config,
            dependencies_files,
            initialise_backend=request.initialise_backend,
        ),
    )

    merged_fetched_deps = await Get(Digest, MergeDigests([x[1] for x in fetched_deps.fetched_deps]))

    sources_and_deps = await Get(
        Digest,
        MergeDigests(
            [source_files.snapshot.digest, merged_fetched_deps, dependencies_files.snapshot.digest]
        ),
    )

    assert len(files_by_directory) == 1, "Multiple directories found, unable to identify a root"
    chdir, files = next(iter(files_by_directory.items()))
    return TerraformInitResponse(sources_and_deps, tuple(files), chdir)


def rules():
    return collect_rules()
