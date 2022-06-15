# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.docker.goals.package_image import DockerFieldSet
from pants.backend.docker.subsystems import dockerfile_parser
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules import (
    docker_binary,
    docker_build_args,
    docker_build_context,
    docker_build_env,
    dockerfile,
)
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
)
from pants.backend.helm.dependency_inference import deployment
from pants.backend.helm.dependency_inference.deployment import FirstPartyHelmDeploymentMappings
from pants.backend.helm.subsystems import post_renderer
from pants.backend.helm.subsystems.post_renderer import (
    PostRendererLauncherSetup,
    SetupPostRendererLauncher,
)
from pants.backend.helm.target_types import HelmDeploymentFieldSet, HelmDeploymentTarget
from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.deployment import FindHelmDeploymentChart
from pants.backend.helm.util_rules.process import HelmRenderCmd, HelmRenderProcess
from pants.backend.helm.util_rules.yaml_utils import HelmManifestItems
from pants.core.goals.deploy import DeployFieldSet, DeployProcess, DeployProcesses, DeploySubsystem
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address, Addresses
from pants.engine.process import InteractiveProcess, InteractiveProcessRequest, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Targets
from pants.engine.unions import UnionRule
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeployHelmDeploymentFieldSet(HelmDeploymentFieldSet, DeployFieldSet):
    pass


_VALID_PASSTHROUGH_FLAGS = [
    "--atomic",
    "--dry-run",
    "--debug",
    "--force",
    "--replace",
    "--wait",
    "--wait-for-jobs",
]

_VALID_PASSTHROUGH_OPTS = [
    "--kubeconfig",
    "--kube-context",
    "--kube-apiserver",
    "--kube-as-group",
    "--kube-as-user",
    "--kube-ca-file",
    "--kube-token",
    "--set",
    "--set-string",
]


class InvalidDeploymentArgs(Exception):
    def __init__(self, args: Iterable[str]) -> None:
        super().__init__(
            softwrap(
                f"""
                The following command line arguments are not valid: {' '.join(args)}.

                Only the following passthrough arguments are allowed:

                {bullet_list([*_VALID_PASSTHROUGH_FLAGS, *_VALID_PASSTHROUGH_OPTS])}

                Most invalid arguments have equivalent fields in the `{HelmDeploymentTarget.alias}` target.
                Usage of fields is encouraged over passthrough arguments as that enables repeatable deployments.

                Please run `{bin_name()} help {HelmDeploymentTarget.alias}` for more information.
                """
            )
        )


@rule(desc="Run Helm deploy process", level=LogLevel.DEBUG)
async def run_helm_deploy(
    field_set: DeployHelmDeploymentFieldSet,
    deploy: DeploySubsystem,
) -> DeployProcesses:
    valid_args, invalid_args = _cleanup_passthrough_args(deploy.args)
    if invalid_args:
        raise InvalidDeploymentArgs(invalid_args)

    chart, values_files = await MultiGet(
        Get(HelmChart, FindHelmDeploymentChart(field_set)),
        Get(
            StrippedSourceFiles,
            SourceFilesRequest([field_set.sources]),
        ),
    )

    release_name = field_set.release_name.value or field_set.address.target_name
    post_renderer = await Get(PostRendererLauncherSetup, DeployHelmDeploymentFieldSet, field_set)
    helm_cmd = await Get(
        Process,
        HelmRenderProcess(
            cmd=HelmRenderCmd.UPGRADE,
            release_name=release_name,
            chart_path=chart.path,
            chart_digest=chart.snapshot.digest,
            description=field_set.description.value,
            namespace=field_set.namespace.value,
            skip_crds=field_set.skip_crds.value,
            no_hooks=field_set.no_hooks.value,
            values_snapshot=values_files.snapshot,
            values=field_set.values.value,
            extra_argv=[
                "--install",
                *(("--create-namespace",) if field_set.create_namespace.value else ()),
                *valid_args,
            ],
            post_renderer_exe=post_renderer.exe,
            post_renderer_digest=post_renderer.input_digest,
            extra_env=post_renderer.env,
            extra_immutable_input_digests=post_renderer.immutable_input_digests,
            extra_append_only_caches=post_renderer.append_only_caches,
            message=(
                f"Deploying release `{release_name}` using chart "
                f"{chart.address} and values from {field_set.address}."
            ),
        ),
    )

    process = await Get(InteractiveProcess, InteractiveProcessRequest(helm_cmd))
    return DeployProcesses([DeployProcess(name=field_set.address.spec, process=process)])


@rule
async def prepare_post_renderer(
    field_set: DeployHelmDeploymentFieldSet,
    mappings: FirstPartyHelmDeploymentMappings,
    docker_options: DockerOptions,
) -> PostRendererLauncherSetup:
    docker_addresses = mappings.docker_images[field_set.address]
    docker_contexts = await MultiGet(
        Get(
            DockerBuildContext,
            DockerBuildContextRequest(
                address=addr,
                build_upstream_images=False,
            ),
        )
        for addr in docker_addresses.values()
    )

    docker_targets = await Get(Targets, Addresses(docker_addresses.values()))
    field_sets = [DockerFieldSet.create(tgt) for tgt in docker_targets]

    def resolve_docker_image_ref(address: Address, context: DockerBuildContext) -> str | None:
        docker_field_sets = [fs for fs in field_sets if fs.address == address]
        if not docker_field_sets:
            return None

        result = None
        docker_field_set = docker_field_sets[0]
        image_refs = docker_field_set.image_refs(
            default_repository=docker_options.default_repository,
            registries=docker_options.registries(),
            interpolation_context=context.interpolation_context,
        )
        if image_refs:
            result = image_refs[0]
        return result

    docker_addr_ref_mapping = {
        addr: resolve_docker_image_ref(addr, ctx)
        for addr, ctx in zip(docker_addresses.values(), docker_contexts)
    }
    replacements = HelmManifestItems(
        {
            manifest: {
                path: str(docker_addr_ref_mapping[address])
                for path, address in docker_addresses.manifest_items(manifest)
                if docker_addr_ref_mapping[address]
            }
            for manifest in docker_addresses.manifests()
        }
    )

    return await Get(PostRendererLauncherSetup, SetupPostRendererLauncher(replacements))


def _cleanup_passthrough_args(args: Iterable[str]) -> tuple[list[str], list[str]]:
    valid_args: list[str] = []
    removed_args: list[str] = []

    skip = False
    for arg in list(args):
        if skip:
            valid_args.append(arg)
            skip = False
            continue

        if arg in _VALID_PASSTHROUGH_FLAGS:
            valid_args.append(arg)
        elif "=" in arg and arg.split("=")[0] in _VALID_PASSTHROUGH_OPTS:
            valid_args.append(arg)
        elif arg in _VALID_PASSTHROUGH_OPTS:
            valid_args.append(arg)
            skip = True
        else:
            removed_args.append(arg)

    return (valid_args, removed_args)


def rules():
    return [
        *collect_rules(),
        *deployment.rules(),
        *docker_binary.rules(),
        *docker_build_args.rules(),
        *docker_build_context.rules(),
        *docker_build_env.rules(),
        *dockerfile.rules(),
        *dockerfile_parser.rules(),
        *post_renderer.rules(),
        UnionRule(DeployFieldSet, DeployHelmDeploymentFieldSet),
    ]
