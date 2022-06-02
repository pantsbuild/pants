# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain

from pants.backend.docker.goals.package_image import DockerFieldSet
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import AllDockerImageTargets
from pants.backend.docker.util_rules import (
    docker_build_args,
    docker_build_context,
    docker_build_env,
    dockerfile,
)
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
)
from pants.backend.helm.target_types import HelmDeploymentDependenciesField, HelmDeploymentFieldSet
from pants.backend.helm.util_rules import deployment, k8s, render
from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.k8s import ImageRef, KubeManifests, ParseKubeManifests
from pants.backend.helm.util_rules.render import RenderedHelmChart, RenderHelmChartRequest
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address, Addresses
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies, WrappedTarget
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalyseHelmDeploymentRequest:
    field_set: HelmDeploymentFieldSet


@dataclass(frozen=True)
class HelmDeploymentReport:
    container_images: OrderedSet[ImageRef]


@rule
async def analyse_deployment(request: AnalyseHelmDeploymentRequest) -> HelmDeploymentReport:
    chart, value_files = await MultiGet(
        Get(HelmChart, HelmDeploymentFieldSet, request.field_set),
        Get(StrippedSourceFiles, SourceFilesRequest([request.field_set.sources])),
    )

    rendered_chart = await Get(
        RenderedHelmChart,
        RenderHelmChartRequest(
            chart,
            skip_crds=request.field_set.skip_crds.value,
            values_snapshot=value_files.snapshot,
            values=request.field_set.values.value,
        ),
    )

    manifests = await Get(
        KubeManifests,
        ParseKubeManifests(rendered_chart.snapshot.digest, request.field_set.address.spec),
    )

    return HelmDeploymentReport(
        container_images=OrderedSet(
            chain.from_iterable([manifest.container_images for manifest in manifests])
        )
    )


@dataclass(frozen=True)
class HelmDeploymentContainerMapping:
    containers: FrozenDict[ImageRef, Address]


@rule
async def build_helm_deployment_mapping(
    all_targets: AllDockerImageTargets, docker_options: DockerOptions
) -> HelmDeploymentContainerMapping:
    docker_field_sets = [DockerFieldSet.create(tgt) for tgt in all_targets]
    docker_contexts = await MultiGet(
        Get(
            DockerBuildContext,
            DockerBuildContextRequest(
                address=field_set.address,
                build_upstream_images=False,
            ),
        )
        for field_set in docker_field_sets
    )

    def parse_container_ref(
        field_set: DockerFieldSet, context: DockerBuildContext
    ) -> list[ImageRef]:
        image_refs = field_set.image_refs(
            default_repository=docker_options.default_repository,
            registries=docker_options.registries(),
            interpolation_context=context.interpolation_context,
        )
        return [ImageRef.parse(ref) for ref in image_refs]

    docker_image_refs = {
        container_ref: field_set.address
        for field_set, context in zip(docker_field_sets, docker_contexts)
        for container_ref in parse_container_ref(field_set, context)
    }
    return HelmDeploymentContainerMapping(containers=FrozenDict(docker_image_refs))


class InjectHelmDeploymentDependenciesRequest(InjectDependenciesRequest):
    inject_for = HelmDeploymentDependenciesField


@rule(desc="Find the dependencies needed by a Helm deployment", level=LogLevel.DEBUG)
async def inject_deployment_dependencies(
    request: InjectHelmDeploymentDependenciesRequest, mapping: HelmDeploymentContainerMapping
) -> InjectedDependencies:
    wrapped_target = await Get(WrappedTarget, Address, request.dependencies_field.address)
    field_set = HelmDeploymentFieldSet.create(wrapped_target.target)
    report = await Get(HelmDeploymentReport, AnalyseHelmDeploymentRequest(field_set))

    logging.debug(
        f"Target {request.dependencies_field.address} references {pluralize(len(report.container_images), 'image')}."
    )

    found_docker_image_addresses = [
        address
        for container_ref, address in mapping.containers.items()
        if container_ref in report.container_images
    ]

    logging.debug(
        f"Found {pluralize(len(found_docker_image_addresses), 'dependency')} for target {request.dependencies_field.address}"
    )

    return InjectedDependencies(Addresses(found_docker_image_addresses))


def rules():
    return [
        *collect_rules(),
        *deployment.rules(),
        *k8s.rules(),
        *render.rules(),
        *docker_build_context.rules(),
        *docker_build_args.rules(),
        *docker_build_env.rules(),
        *dockerfile.rules(),
        UnionRule(InjectDependenciesRequest, InjectHelmDeploymentDependenciesRequest),
    ]
