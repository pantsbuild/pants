# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Union

from pants.backend.terraform.dependencies import TerraformInitRequest, TerraformInitResponse
from pants.backend.terraform.target_types import (
    TerraformBackendConfigField,
    TerraformDependenciesField,
    TerraformDeploymentTarget,
    TerraformRootModuleField,
)
from pants.backend.terraform.tool import TerraformProcess
from pants.core.goals.generate_lockfiles import (
    GenerateLockfile,
    GenerateLockfileResult,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
)
from pants.engine.addresses import Addresses
from pants.engine.internals.native_engine import Address
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import AllTargets, Targets
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class GenerateTerraformLockfile(GenerateLockfile):
    target: TerraformDeploymentTarget


class KnownTerraformResolveNamesRequest(KnownUserResolveNamesRequest):
    pass


class RequestedTerraformResolveNames(RequestedUserResolveNames):
    pass


@rule
async def identify_user_resolves_from_terraform_files(
    _: KnownTerraformResolveNamesRequest,
    all_targets: AllTargets,
) -> KnownUserResolveNames:
    known_terraform_module_dirs = []
    for tgt in all_targets:
        if tgt.has_field(TerraformRootModuleField):
            known_terraform_module_dirs.append(tgt.residence_dir)

    return KnownUserResolveNames(
        names=tuple(known_terraform_module_dirs),
        option_name="[terraform].resolves",
        requested_resolve_names_cls=RequestedTerraformResolveNames,
    )


@rule
async def setup_user_lockfile_requests(
    requested: RequestedTerraformResolveNames,
) -> UserGenerateLockfiles:
    [tgt] = await Get(Targets, Addresses([Address(requested[0])]))
    assert isinstance(tgt, TerraformDeploymentTarget)

    return UserGenerateLockfiles(
        [
            GenerateTerraformLockfile(
                target=tgt,
                resolve_name=requested[0],
                lockfile_dest=(Path(tgt.residence_dir) / ".terraform.lock.hcl").as_posix(),
                diff=False,
            )
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
            lockfile_request.target[TerraformRootModuleField],
            lockfile_request.target[TerraformBackendConfigField],
            lockfile_request.target[TerraformDependenciesField],
            initialise_backend=False,
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


def rules() -> Iterable[Union[Rule, UnionRule]]:
    return (
        *collect_rules(),
        UnionRule(GenerateLockfile, GenerateTerraformLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownTerraformResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedTerraformResolveNames),
    )