# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
from dataclasses import dataclass
from pathlib import Path

from pants.backend.terraform.dependencies import TerraformInitRequest, prepare_terraform_invocation
from pants.backend.terraform.target_types import (
    TerraformDependenciesField,
    TerraformLockfileTarget,
    TerraformModuleSourcesField,
    TerraformModuleTarget,
    TerraformRootModuleField,
)
from pants.backend.terraform.tool import TerraformCommand, TerraformProcess, TerraformTool
from pants.backend.terraform.utils import terraform_arg
from pants.core.goals.generate_lockfiles import (
    GenerateLockfile,
    GenerateLockfileResult,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
)
from pants.engine.addresses import Addresses
from pants.engine.fs import PathGlobs
from pants.engine.internals.build_files import resolve_address
from pants.engine.internals.graph import resolve_targets
from pants.engine.internals.native_engine import AddressInput, MergeDigests
from pants.engine.internals.selectors import concurrently
from pants.engine.internals.synthetic_targets import SyntheticAddressMaps, SyntheticTargetsRequest
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.intrinsics import digest_to_snapshot, execute_process, merge_digests
from pants.engine.process import ProcessExecutionFailure
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import AllTargets
from pants.engine.unions import UnionRule
from pants.option.global_options import KeepSandboxes


class KnownTerraformResolveNamesRequest(KnownUserResolveNamesRequest):
    pass


class RequestedTerraformResolveNames(RequestedUserResolveNames):
    pass


@rule
async def identify_user_resolves_from_terraform_files(
    _: KnownTerraformResolveNamesRequest,
    all_targets: AllTargets,
) -> KnownUserResolveNames:
    """We don't use the TerraformSyntheticLockfileTargetsRequest because those only include
    lockfiles that have been written and not new lockfiles."""
    known_terraform_module_dirs = set()

    for tgt in all_targets:
        if tgt.has_field(TerraformModuleSourcesField):
            known_terraform_module_dirs.add(tgt.address.spec)

    return KnownUserResolveNames(
        names=tuple(known_terraform_module_dirs),
        option_name="[terraform].resolves",
        requested_resolve_names_cls=RequestedTerraformResolveNames,
    )


@dataclass(frozen=True)
class GenerateTerraformLockfile(GenerateLockfile):
    target: TerraformModuleTarget
    platforms: tuple[str, ...]


@rule
async def setup_user_lockfile_requests(
    requested: RequestedTerraformResolveNames,
    terraform: TerraformTool,
) -> UserGenerateLockfiles:
    addrs = await concurrently(
        resolve_address(
            **implicitly(
                {
                    AddressInput.parse(
                        m, description_of_origin="setup Terraform lockfiles"
                    ): AddressInput
                }
            )
        )
        for m in requested
    )

    targets = await resolve_targets(**implicitly(Addresses(addrs)))
    deployment_targets = [t for t in targets if isinstance(t, TerraformModuleTarget)]

    return UserGenerateLockfiles(
        [
            GenerateTerraformLockfile(
                target=tgt,
                platforms=terraform.platforms,
                resolve_name=tgt.residence_dir,
                lockfile_dest=(Path(tgt.residence_dir) / ".terraform.lock.hcl").as_posix(),
                diff=False,
            )
            for tgt in deployment_targets
        ]
    )


@rule
async def generate_lockfile_from_sources(
    lockfile_request: GenerateTerraformLockfile,
    keep_sandboxes: KeepSandboxes,
) -> GenerateLockfileResult:
    """Generate a Terraform lockfile by running `terraform providers lock` on the sources."""
    initialised_terraform = await prepare_terraform_invocation(
        TerraformInitRequest(
            TerraformRootModuleField(
                lockfile_request.target.address.spec, lockfile_request.target.address
            ),
            lockfile_request.target[TerraformDependenciesField],
            initialise_backend=False,
            upgrade=True,
        )
    )

    sources_and_deps = await merge_digests(
        MergeDigests(
            [
                initialised_terraform.terraform_sources.snapshot.digest,
                initialised_terraform.dependencies_files.snapshot.digest,
            ]
        )
    )

    args = (
        "providers",
        "lock",
        *(terraform_arg("-platform", platform) for platform in lockfile_request.platforms),
    )

    provider_lock_description = f"Update terraform lockfile for {lockfile_request.resolve_name}"
    multiplatform_lockfile = await execute_process(
        **implicitly(
            TerraformProcess(
                cmds=(
                    initialised_terraform.init_cmd.to_args(),
                    TerraformCommand(args),
                ),
                input_digest=sources_and_deps,
                output_files=(".terraform.lock.hcl",),
                description=provider_lock_description,
                chdir=initialised_terraform.chdir,
            )
        )
    )
    if multiplatform_lockfile.exit_code != 0:
        raise ProcessExecutionFailure(
            multiplatform_lockfile.exit_code,
            multiplatform_lockfile.stdout,
            multiplatform_lockfile.stderr,
            provider_lock_description,
            keep_sandboxes=keep_sandboxes,
        )

    return GenerateLockfileResult(
        multiplatform_lockfile.output_digest,
        lockfile_request.resolve_name,
        lockfile_request.lockfile_dest,
    )


@dataclass(frozen=True)
class TerraformSyntheticLockfileTargetsRequest(SyntheticTargetsRequest):
    path: str = SyntheticTargetsRequest.REQUEST_TARGETS_PER_DIRECTORY


@rule
async def terraform_lockfile_synthetic_targets(
    request: TerraformSyntheticLockfileTargetsRequest,
) -> SyntheticAddressMaps:
    path = request.path
    lockfile = await digest_to_snapshot(
        **implicitly(PathGlobs([Path(path, ".terraform.lock.hcl").as_posix()]))
    )
    if not lockfile.files:
        return SyntheticAddressMaps(tuple())

    return SyntheticAddressMaps.for_targets_request(
        request,
        [
            (
                os.path.join(path, "BUILD.terraform-lockfiles"),
                (
                    TargetAdaptor(
                        TerraformLockfileTarget.alias,
                        name=".terraform.lock.hcl",
                        source=".terraform.lock.hcl",
                        __description_of_origin__="terraform",
                    ),
                ),
            )
        ],
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateLockfile, GenerateTerraformLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownTerraformResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedTerraformResolveNames),
        UnionRule(SyntheticTargetsRequest, TerraformSyntheticLockfileTargetsRequest),
    )
