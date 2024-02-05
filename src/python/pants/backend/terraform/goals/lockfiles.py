# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from pants.backend.terraform.dependencies import TerraformInitRequest, TerraformInitResponse
from pants.backend.terraform.target_types import (
    TerraformDependenciesField,
    TerraformDeploymentTarget,
    TerraformModuleSourcesField,
    TerraformModuleTarget,
    TerraformRootModuleField,
)
from pants.backend.terraform.tool import TerraformProcess
from pants.core.goals.generate_lockfiles import GenerateLockfileResult
from pants.core.goals.resolve_helpers import (
    GenerateLockfile,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
)
from pants.engine.addresses import Addresses
from pants.engine.internals.native_engine import Address, AddressInput
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import AllTargets, Targets
from pants.engine.unions import UnionRule


class KnownTerraformResolveNamesRequest(KnownUserResolveNamesRequest):
    pass


class RequestedTerraformResolveNames(RequestedUserResolveNames):
    pass


@rule
async def identify_user_resolves_from_terraform_files(
    _: KnownTerraformResolveNamesRequest,
    all_targets: AllTargets,
) -> KnownUserResolveNames:
    known_terraform_module_dirs = set()

    for tgt in all_targets:
        if tgt.has_field(TerraformModuleSourcesField):
            known_terraform_module_dirs.add(tgt.address.spec)
        if tgt.has_field(TerraformRootModuleField):
            known_terraform_module_dirs.add(tgt.address.spec)

    return KnownUserResolveNames(
        names=tuple(known_terraform_module_dirs),
        option_name="[terraform].resolves",
        requested_resolve_names_cls=RequestedTerraformResolveNames,
    )


@dataclass(frozen=True)
class GenerateTerraformLockfile(GenerateLockfile):
    target: Union[TerraformModuleTarget, TerraformDeploymentTarget]


@rule
async def setup_user_lockfile_requests(
    requested: RequestedTerraformResolveNames,
) -> UserGenerateLockfiles:
    addrs = await MultiGet(
        Get(
            Address,
            AddressInput,
            AddressInput.parse(m, description_of_origin="setup Terraform lockfiles"),
        )
        for m in requested
    )

    targets = await Get(Targets, Addresses, Addresses(addrs))
    module_targets = [t for t in targets if isinstance(t, TerraformModuleTarget)]
    deployment_targets = [t for t in targets if isinstance(t, TerraformDeploymentTarget)]
    targets_with_resolves: list[Union[TerraformModuleTarget, TerraformDeploymentTarget]] = [
        *module_targets,
        *deployment_targets,
    ]

    return UserGenerateLockfiles(
        [
            GenerateTerraformLockfile(
                target=tgt,
                resolve_name=tgt.address.spec,
                lockfile_dest=(Path(tgt.residence_dir) / ".terraform.lock.hcl").as_posix(),
                diff=False,
            )
            for tgt in targets_with_resolves
        ]
    )


@rule
async def generate_lockfile_from_sources(
    lockfile_request: GenerateTerraformLockfile,
) -> GenerateLockfileResult:
    """Generate a Terraform lockfile by running `terraform providers lock` on the sources."""
    initialised_terraform = await Get(
        TerraformInitResponse,
        TerraformInitRequest(
            TerraformRootModuleField(
                lockfile_request.target.address.spec, lockfile_request.target.address
            ),
            lockfile_request.target[TerraformDependenciesField],
            initialise_backend=False,
            upgrade=True,
        ),
    )
    result = await Get(
        ProcessResult,
        TerraformProcess(
            args=(
                "providers",
                "lock",
            ),
            input_digest=initialised_terraform.sources_and_deps,
            output_files=(".terraform.lock.hcl",),
            description=f"Update terraform lockfile for {lockfile_request.resolve_name}",
            chdir=initialised_terraform.chdir,
        ),
    )

    return GenerateLockfileResult(
        result.output_digest, lockfile_request.resolve_name, lockfile_request.lockfile_dest
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateLockfile, GenerateTerraformLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownTerraformResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedTerraformResolveNames),
    )
