# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, unique
from itertools import chain
from typing import Any, cast

import yaml

from pants.backend.docker.goals.package_image import DockerFieldSet
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
)
from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmDeploymentDependenciesField,
    HelmDeploymentFieldSet,
)
from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.render import RenderChartRequest, RenderedChart
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    AllTargets,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    Targets,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


class MissingHelmDeploymentChartError(ValueError):
    pass


class TooManyChartDependenciesError(ValueError):
    pass


@unique
class ResourceKind(Enum):
    """The kind of Kubernetes resource."""

    CONFIG_MAP = "ConfigMap"
    CRON_JOB = "CronJob"
    DAEMON_SET = "DaemonSet"
    DEPLOYMENT = "Deployment"
    INGRESS = "Ingress"
    PERSISTENT_VOLUME = "PersistentVolume"
    PERSISTENT_VOLUME_CLAIM = "PersistentVolumeClaim"
    POD = "Pod"
    JOB = "Job"
    REPLICA_SET = "ReplicaSet"
    SECRET = "Secret"
    SERVICE = "Service"
    STATEFUL_SET = "StatefulSet"


_DEFAULT_CONTAINER_TAG = "latest"


@dataclass(frozen=True)
class CustomResourceKind:
    value: str


@dataclass(frozen=True)
class ContainerRef:
    registry: str | None
    repository: str
    tag: str = _DEFAULT_CONTAINER_TAG

    @classmethod
    def parse(cls, image_ref: str) -> ContainerRef:
        registry = None
        tag = _DEFAULT_CONTAINER_TAG

        addr_and_tag = image_ref.split(":")
        if len(addr_and_tag) > 1:
            tag = addr_and_tag[1]

        slash_idx = addr_and_tag[0].find("/")
        if slash_idx >= 0:
            registry = addr_and_tag[0][:slash_idx]
            repo = addr_and_tag[0][(slash_idx + 1) :]
        else:
            repo = addr_and_tag[0]

        return cls(registry=registry, repository=repo, tag=tag)

    def __str__(self) -> str:
        return f"{self.registry}/{self.repository}:{self.tag}"


@dataclass(frozen=True)
class ResourceManifest:
    api_version: str
    kind: ResourceKind | CustomResourceKind
    container_images: tuple[ContainerRef, ...]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ResourceManifest:
        std_kind: ResourceKind | None = None
        try:
            std_kind = ResourceKind(d["kind"])
        except ValueError:
            custom_kind = CustomResourceKind(d["kind"])

        container_images: list[ContainerRef] = []
        if std_kind:
            container_images = cls._extract_container_images(std_kind, d["spec"])

        return cls(
            api_version=d["apiVersion"],
            kind=std_kind or custom_kind,
            container_images=tuple(container_images),
        )

    @classmethod
    def _extract_container_images(
        cls, kind: ResourceKind, spec: dict[str, Any]
    ) -> list[ContainerRef]:
        def safe_get(path: list[str]) -> Any | None:
            lookup_from = spec
            result = None
            for path_elem in path:
                result = lookup_from.get(path_elem)
                lookup_from = result or {}
                if not result:
                    break
            return result

        def get_containers(spec_path: list[str]) -> list[dict[str, Any]]:
            cs = safe_get([*spec_path, "containers"]) or []
            cs.extend(safe_get([*spec_path, "initContainers"]) or [])
            return cs

        containers = []
        if kind == ResourceKind.CRON_JOB:
            containers = get_containers(["jobTemplate", "spec", "template", "spec"])
        elif kind == ResourceKind.DAEMON_SET:
            containers = get_containers(["template", "spec"])
        elif kind == ResourceKind.DEPLOYMENT:
            containers = get_containers(["template", "spec"])
        elif kind == ResourceKind.JOB:
            containers = get_containers(["template", "spec"])
        elif kind == ResourceKind.POD:
            containers = get_containers([])
        elif kind == ResourceKind.REPLICA_SET:
            containers = get_containers(["template", "spec"])
        elif kind == ResourceKind.STATEFUL_SET:
            containers = get_containers(["template", "spec"])

        return [ContainerRef.parse(cast(str, container["image"])) for container in containers]


@dataclass(frozen=True)
class AnalyseDeploymentRequest:
    field_set: HelmDeploymentFieldSet


@dataclass(frozen=True)
class AnalysedDeployment:
    container_images: tuple[ContainerRef, ...]


class InjectHelmDeploymentDependenciesRequest(InjectDependenciesRequest):
    inject_for = HelmDeploymentDependenciesField


@rule
async def get_chart_via_deployment(field_set: HelmDeploymentFieldSet) -> HelmChart:
    explicit_dependencies = await Get(
        ExplicitlyProvidedDependencies, DependenciesRequest(field_set.dependencies)
    )
    explicit_targets = await Get(
        Targets,
        Addresses(
            [
                addr
                for addr in explicit_dependencies.includes
                if addr not in explicit_dependencies.ignores
            ]
        ),
    )

    found_charts = [tgt for tgt in explicit_targets if HelmChartFieldSet.is_applicable(tgt)]
    if not found_charts:
        raise MissingHelmDeploymentChartError(
            f"The target address '{field_set.address}' is missing a dependency on a `helm_chart` target."
        )
    if len(found_charts) > 1:
        raise TooManyChartDependenciesError(
            f"The target address '{field_set.address}' has too many `helm_chart` addresses in its dependencies, it should have only one."
        )

    chart_fs = HelmChartFieldSet.create(found_charts[0])
    return await Get(HelmChart, HelmChartFieldSet, chart_fs)


@rule(desc="Analyse Helm deployment dependencies", level=LogLevel.DEBUG)
async def analyse_deployment_dependencies(request: AnalyseDeploymentRequest) -> AnalysedDeployment:
    chart, value_files = await MultiGet(
        Get(HelmChart, HelmDeploymentFieldSet, request.field_set),
        Get(
            StrippedSourceFiles,
            SourceFilesRequest([request.field_set.sources]),
        ),
    )

    rendered_chart = await Get(
        RenderedChart,
        RenderChartRequest(
            chart,
            value_files=value_files.snapshot,
            values=request.field_set.values.value or FrozenDict[str, str](),
        ),
    )
    file_contents = await Get(DigestContents, Digest, rendered_chart.snapshot.digest)

    manifests = [
        ResourceManifest.from_dict(parsed_yaml)
        for file in file_contents
        for parsed_yaml in yaml.safe_load_all(file.content)
    ]
    logger.debug(
        f"Found {pluralize(len(manifests), 'manifest')} in the chart '{chart.metadata.name}' rendered by deployment at: {request.field_set.address}"
    )
    return AnalysedDeployment(
        container_images=tuple(
            chain.from_iterable([manifest.container_images for manifest in manifests])
        )
    )


@rule(desc="Find container images being used by a Helm deployment", level=LogLevel.DEBUG)
async def inject_deployment_dependencies(
    request: InjectHelmDeploymentDependenciesRequest,
    all_targets: AllTargets,
    docker_options: DockerOptions,
) -> InjectedDependencies:
    wrapped_target = await Get(WrappedTarget, Address, request.dependencies_field.address)
    field_set = HelmDeploymentFieldSet.create(wrapped_target.target)
    analysis = await Get(AnalysedDeployment, AnalyseDeploymentRequest(field_set))

    logging.debug(
        f"Found {pluralize(len(analysis.container_images), 'image')} for target at address: {request.dependencies_field.address}"
    )

    docker_field_sets = [
        DockerFieldSet.create(tgt) for tgt in all_targets if DockerFieldSet.is_applicable(tgt)
    ]
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

    docker_image_refs = [
        (
            field_set.address,
            field_set.image_refs(
                default_repository=docker_options.default_repository,
                registries=docker_options.registries(),
                interpolation_context=context.interpolation_context,
            ),
        )
        for field_set, context in zip(docker_field_sets, docker_contexts)
    ]
    found_docker_image_addresses = [
        address
        for address, container_refs in docker_image_refs
        for container_ref in container_refs
        if ContainerRef.parse(container_ref) in analysis.container_images
    ]

    return InjectedDependencies(Addresses(found_docker_image_addresses))


def rules():
    return [
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectHelmDeploymentDependenciesRequest),
    ]
