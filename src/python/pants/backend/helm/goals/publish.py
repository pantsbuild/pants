# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.helm.goals.package import BuiltHelmArtifact
from pants.backend.helm.resolve.remotes import HelmRegistry
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartRepositoryField,
    HelmRegistriesField,
    HelmSkipPushField,
)
from pants.backend.helm.util_rules.chart import HelmChartRequest, get_helm_chart
from pants.backend.helm.util_rules.tool import HelmProcess, helm_process
from pants.core.goals.package import PackageFieldSet
from pants.core.goals.publish import (
    CheckSkipRequest,
    CheckSkipResult,
    PublishFieldSet,
    PublishOutputData,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
)
from pants.engine.process import InteractiveProcess
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class PublishHelmChartRequest(PublishRequest):
    pass


@dataclass(frozen=True)
class HelmPublishFieldSet(HelmChartFieldSet, PublishFieldSet):
    publish_request_type = PublishHelmChartRequest

    registries: HelmRegistriesField
    repository: HelmChartRepositoryField
    skip_push: HelmSkipPushField

    def make_skip_request(self, package_fs: PackageFieldSet) -> PublishHelmChartSkipRequest | None:
        return PublishHelmChartSkipRequest(publish_fs=self, package_fs=package_fs)

    def get_output_data(self) -> PublishOutputData:
        return PublishOutputData(
            {
                "publisher": "helm",
                "registries": self.registries.value or (),
                **super().get_output_data(),
            }
        )


class PublishHelmChartSkipRequest(CheckSkipRequest[HelmPublishFieldSet]):
    pass


def get_helm_registries(
    helm_subsystem: HelmSubsystem, registries: Iterable[str] | None
) -> list[HelmRegistry]:
    return list(helm_subsystem.remotes().get(*(registries or [])))


@rule
async def check_if_skip_push(
    request: PublishHelmChartSkipRequest, helm_subsystem: HelmSubsystem
) -> CheckSkipResult:
    registries_to_push = get_helm_registries(helm_subsystem, request.publish_fs.registries.value)
    if registries_to_push and not request.publish_fs.skip_push.value:
        return CheckSkipResult.no_skip()
    reason = (
        f"missing `{request.publish_fs.registries.alias}`"
        if not registries_to_push
        else f"`{request.publish_fs.skip_push.alias}`"
    )
    chart = await get_helm_chart(HelmChartRequest(request.publish_fs), **implicitly())
    return CheckSkipResult.skip(
        names=[chart.info.artifact_name],
        description=f"(by {reason} on {request.publish_fs.address})",
        data=request.publish_fs.get_output_data(),
    )


@rule(desc="Push Helm chart to OCI registries", level=LogLevel.DEBUG)
async def publish_helm_chart(
    request: PublishHelmChartRequest, helm_subsystem: HelmSubsystem
) -> PublishProcesses:
    built_artifacts = [
        (pkg, artifact, artifact.info)
        for pkg in request.packages
        for artifact in pkg.artifacts
        if isinstance(artifact, BuiltHelmArtifact) and artifact.info
    ]

    registries_to_push = get_helm_registries(helm_subsystem, request.field_set.registries.value)
    push_repository = (
        request.field_set.repository.value or helm_subsystem.default_registry_repository
    )
    publish_refs = [
        registry.package_ref(metadata.artifact_name, repository=push_repository)
        for _, _, metadata in built_artifacts
        for registry in registries_to_push
    ]
    processes = await concurrently(
        helm_process(
            HelmProcess(
                ["push", artifact.relpath, registry.repository_ref(push_repository)],
                input_digest=pkg.digest,
                description=f"Pushing Helm chart '{metadata.name}' with version '{metadata.version}' into OCI registry: {registry.address}",
            ),
            **implicitly(),
        )
        for pkg, artifact, metadata in built_artifacts
        if artifact.relpath
        for registry in registries_to_push
    )

    return PublishProcesses(
        [
            PublishPackages(names=(package_ref,), process=InteractiveProcess.from_process(process))
            for package_ref, process in zip(publish_refs, processes)
        ]
    )


def rules():
    return [
        *collect_rules(),
        *HelmPublishFieldSet.rules(),
        UnionRule(CheckSkipRequest, PublishHelmChartSkipRequest),
    ]
