# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
import os.path
from dataclasses import dataclass
from typing import Optional

from pants.backend.terraform.dependency_inference import (
    TerraformDeploymentInvocationFiles,
    TerraformDeploymentInvocationFilesRequest,
)
from pants.backend.terraform.target_types import (
    TerraformDependenciesField,
    TerraformRootModuleField,
)
from pants.backend.terraform.tool import TerraformProcess, TerraformTool
from pants.backend.terraform.utils import terraform_arg, terraform_relpath
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import DigestSubset, PathGlobs
from pants.engine.internals.native_engine import Address, AddressInput, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, ProcessExecutionFailure
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    SourcesField,
    TransitiveTargets,
    TransitiveTargetsRequest,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.option.global_options import KeepSandboxes


@dataclass(frozen=True)
class TerraformDependenciesRequest:
    chdir: str
    backend_config: Optional[str]
    lockfile: bool
    dependencies_files: Digest

    # Not initialising the backend means we won't access remote state. Useful for `validate`
    initialise_backend: bool = False
    upgrade: bool = False


@dataclass(frozen=True)
class TerraformDependenciesResponse:
    digest: Digest


@rule
async def get_terraform_providers(
    req: TerraformDependenciesRequest,
    terraform: TerraformTool,
    keep_sandboxes: KeepSandboxes,
) -> TerraformDependenciesResponse:
    args = ["init"]
    if req.backend_config:
        args.append(
            terraform_arg(
                "-backend-config",
                terraform_relpath(req.chdir, req.backend_config),
            )
        )

    # If we have a lockfile and aren't regenerating it, don't modify it
    if req.lockfile and not req.upgrade:
        args.append("-lockfile=readonly")

    if req.upgrade:
        args.append("-upgrade")

    args.append(terraform_arg("-backend", str(req.initialise_backend)))

    init_process_description = (
        f"Running `init` on Terraform module at `{req.chdir}` to fetch dependencies"
    )
    fetched_deps = await Get(
        FallibleProcessResult,
        TerraformProcess(
            args=tuple(args),
            input_digest=req.dependencies_files,
            output_files=(".terraform.lock.hcl",),
            output_directories=(".terraform",),
            description=init_process_description,
            chdir=req.chdir,
        ),
    )
    if fetched_deps.exit_code != 0:
        raise ProcessExecutionFailure.from_result(
            fetched_deps, init_process_description, keep_sandboxes
        )

    return TerraformDependenciesResponse(fetched_deps.output_digest)


@dataclass(frozen=True)
class TerraformInitRequest:
    root_module: TerraformRootModuleField
    dependencies: TerraformDependenciesField

    # Not initialising the backend means we won't access remote state. Useful for `validate`
    initialise_backend: bool = False


@dataclass(frozen=True)
class TerraformInitResponse:
    sources_and_deps: Digest
    terraform_files: SourceFiles
    chdir: str


@dataclass(frozen=True)
class TerraformUpgradeResponse:
    sources_and_deps: Digest
    lockfile: Digest
    chdir: str


async def run_terraform_init(request: TerraformInitRequest, upgrade: bool):
    """Just run `terraform init`"""
    this_targets_dependencies = await Get(
        TransitiveTargets, TransitiveTargetsRequest((request.dependencies.address,))
    )

    address_input = request.root_module.to_address_input()
    module_address = await Get(Address, AddressInput, address_input)

    chdir = module_address.spec_path  # TODO: spec_path is wrong, that's to the build file
    # if the Terraform module is in the root, chdir will be "". Terraform needs a valid dir to change to
    if not chdir:
        chdir = "."

    # TODO: is this still necessary, or do we pull it in with (transitive) dependencies?
    module = await Get(
        WrappedTarget,
        WrappedTargetRequest(
            module_address, description_of_origin=address_input.description_of_origin
        ),
    )

    source_files, dependencies_files = await MultiGet(
        Get(
            SourceFiles, SourceFilesRequest([module.target.get(SourcesField)])
        ),  # TODO: get through transitive deps???
        Get(
            SourceFiles,
            SourceFilesRequest(
                [tgt.get(SourcesField) for tgt in this_targets_dependencies.dependencies]
            ),
        ),
    )
    invocation_files = await Get(
        TerraformDeploymentInvocationFiles,
        TerraformDeploymentInvocationFilesRequest(
            request.dependencies.address, request.dependencies
        ),
    )
    backend_config_tgts = invocation_files.backend_configs
    if len(backend_config_tgts) == 0:
        backend_config = None
    elif len(backend_config_tgts) == 1:
        backend_config_sources = await Get(
            SourceFiles, SourceFilesRequest([backend_config_tgts[0].get(SourcesField)])
        )
        backend_config = backend_config_sources.snapshot.files[0]
    else:
        # We've found multiple backend files, but that's only a problem if we need to initialise the backend.
        # For example, we might be `validate`ing a `terraform_module` that has multiple backend files in the same dir,
        # so we don't need to init the backend.
        # The `terraform_deployment`s will have the references to the correct backends

        if request.initialise_backend:
            backend_config_names = [e.address for e in backend_config_tgts]
            raise ValueError(
                f"Found more than 1 backend config for a Terraform deployment. identified {backend_config_names}"
            )
        else:
            backend_config = None

    source_for_validate = await Get(
        Digest,
        MergeDigests([source_files.snapshot.digest, dependencies_files.snapshot.digest]),
    )

    has_lockfile = invocation_files.lockfile is not None
    init_response = await Get(
        TerraformDependenciesResponse,
        TerraformDependenciesRequest(
            chdir,
            backend_config,
            has_lockfile,
            source_for_validate,
            initialise_backend=request.initialise_backend,
            upgrade=upgrade,
        ),
    )

    return source_files, dependencies_files, init_response, chdir


@rule
async def terraform_init(request: TerraformInitRequest) -> TerraformInitResponse:
    """Run `terraform init`.

    Returns all the initialised files, ready for execution of subsequent tasks
    """
    source_files, dependencies_files, init_response, chdir = await run_terraform_init(
        request, upgrade=False
    )

    all_terraform_files = await Get(
        Digest,
        MergeDigests(
            [
                source_files.snapshot.digest,
                dependencies_files.snapshot.digest,
                init_response.digest,
            ]
        ),
    )

    return TerraformInitResponse(
        sources_and_deps=all_terraform_files, terraform_files=source_files, chdir=chdir
    )


@rule
async def terraform_upgrade_lockfile(request: TerraformInitRequest) -> TerraformUpgradeResponse:
    """Run `terraform init -upgrade`. Returns all terraform files with the new lockfile.

    This split exists because the new and old lockfile will conflict if merging digests
    """

    source_files, dependencies_files, init_response, chdir = await run_terraform_init(
        request, upgrade=True
    )

    updated_lockfile, dependencies_except_lockfile = await MultiGet(
        Get(
            Digest,
            DigestSubset(
                init_response.digest,
                PathGlobs(
                    (os.path.join(chdir, ".terraform.lock.hcl"),),
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin="upgrade terraform lockfile with `terraform init`",
                ),
            ),
        ),
        Get(
            Digest,
            DigestSubset(
                dependencies_files.snapshot.digest,
                PathGlobs(
                    (
                        "**",
                        "!" + os.path.join(chdir, ".terraform.lock.hcl"),
                    ),
                ),
            ),
        ),
    )

    all_terraform_files = await Get(
        Digest,
        MergeDigests(
            [
                source_files.snapshot.digest,
                dependencies_except_lockfile,
                init_response.digest,
                updated_lockfile,
            ]
        ),
    )

    return TerraformUpgradeResponse(all_terraform_files, updated_lockfile, chdir)


def rules():
    return collect_rules()
