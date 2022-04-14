# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.helm.goals.package import BuiltHelmArtifact
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartRepositoryField,
    HelmRegistriesField,
    HelmSkipPushField,
)
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.core.goals.publish import (
    PublishFieldSet,
    PublishOutputData,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
)
from pants.engine.process import InteractiveProcess, InteractiveProcessRequest, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
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

    def get_output_data(self) -> PublishOutputData:
        return PublishOutputData(
            {
                "publisher": "helm",
                "registries": self.registries.value or (),
                **super().get_output_data(),
            }
        )


@rule(desc="Push Helm chart to OCI registries", level=LogLevel.DEBUG)
async def publish_helm_chart(
    request: PublishHelmChartRequest, helm_subsystem: HelmSubsystem
) -> PublishProcesses:
    remotes = helm_subsystem.remotes()
    built_artifacts = [
        (pkg, artifact, artifact.metadata)
        for pkg in request.packages
        for artifact in pkg.artifacts
        if isinstance(artifact, BuiltHelmArtifact) and artifact.metadata
    ]

    registries_to_push = list(remotes.get(*(request.field_set.registries.value or [])))
    if not registries_to_push:
        return PublishProcesses(
            [
                PublishPackages(
                    names=tuple(metadata.artifact_name for _, _, metadata in built_artifacts),
                    description=f"(by missing `{request.field_set.registries.alias}` on {request.field_set.address})",
                )
            ]
        )

    push_repository = (
        request.field_set.repository.value or helm_subsystem.default_registry_repository
    )
    publish_refs = [
        registry.package_ref(metadata.artifact_name, repository=push_repository)
        for _, _, metadata in built_artifacts
        for registry in registries_to_push
    ]
    if request.field_set.skip_push.value:
        return PublishProcesses(
            [
                PublishPackages(
                    names=tuple(publish_refs),
                    description=f"(by `{request.field_set.skip_push.alias}` on {request.field_set.address})",
                )
            ]
        )

    processes = await MultiGet(
        Get(
            Process,
            HelmProcess(
                ["push", artifact.relpath, registry.repository_ref(push_repository)],
                input_digest=pkg.digest,
                description=f"Pushing Helm chart '{metadata.name}' with version '{metadata.version}' into OCI registry: {registry.address}",
            ),
        )
        for pkg, artifact, metadata in built_artifacts
        if artifact.relpath
        for registry in registries_to_push
    )

    interactive_processes = await MultiGet(
        Get(InteractiveProcess, InteractiveProcessRequest(process)) for process in processes
    )

    refs_and_processes = zip(publish_refs, interactive_processes)
    return PublishProcesses(
        [
            PublishPackages(names=(package_ref,), process=process)
            for package_ref, process in refs_and_processes
        ]
    )


def rules():
    return [*collect_rules(), *HelmPublishFieldSet.rules()]
