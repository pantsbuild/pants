# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain
from os import path
from typing import Any, Mapping, cast

from pants.backend.helm.goals.package import BuiltHelmArtifact
from pants.backend.helm.resolve.registries import HelmRegistries
from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import (
    HelmChartMetaSourceField,
    HelmRegistriesField,
    HelmRepositoryField,
    HelmSkipPushField,
)
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.goals.publish import (
    PublishFieldSet,
    PublishOutputData,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
)
from pants.engine.process import InteractiveProcess, InteractiveProcessRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class HelmArtifactMissingNameError(ValueError):
    pass


class HelmArtifactMissingMetadataError(ValueError):
    pass


class HelmRepositoryNameError(ValueError):
    pass


class PublishHelmChartRequest(PublishRequest):
    pass


@dataclass(frozen=True)
class HelmPublishFieldSet(PublishFieldSet):
    publish_request_type = PublishHelmChartRequest
    required_fields = (HelmChartMetaSourceField, HelmRegistriesField)

    chart: HelmChartMetaSourceField
    registries: HelmRegistriesField
    repository: HelmRepositoryField
    skip_push: HelmSkipPushField

    def get_output_data(self) -> PublishOutputData:
        return PublishOutputData(
            {
                "publisher": "helm",
                "registries": self.registries.value or (),
                **super().get_output_data(),
            }
        )

    def format_repository(
        self, default_repository: str, repository_context: Mapping[str, Any]
    ) -> str:
        fmt_context = dict(
            directory=path.basename(self.address.spec_path),
            name=self.address.target_name,
            parent_directory=path.basename(path.dirname(self.address.spec_path)),
            **repository_context,
        )
        repository_fmt = self.repository.value or default_repository

        try:
            return repository_fmt.format(**fmt_context)
        except (KeyError, ValueError) as e:
            if self.repository.value:
                source = f"`repository` field of the `helm_chart` target at {self.address}"
            else:
                source = "`[helm].default_oci_repository` configuration option"

            msg = f"Invalid value for the {source}: {repository_fmt!r}.\n\n"

            if isinstance(e, KeyError):
                msg += (
                    f"The placeholder {e} is unknown. "
                    f'Try with one of: {", ".join(sorted(fmt_context.keys()))}.'
                )
            else:
                msg += str(e)
            raise HelmRepositoryNameError(msg) from e

    def publish_refs(
        self, artifact: BuiltHelmArtifact, default_repository: str, registries: HelmRegistries
    ) -> tuple[str, ...]:
        if not artifact.name:
            raise HelmArtifactMissingNameError(
                f"Could not obtain Helm chart artifact name since it is missing in target at: {self.address}"
            )
        if not artifact.metadata:
            raise HelmArtifactMissingMetadataError(
                f"Could not obtain Helm chart metadata since it is missing in target at: {self.address}"
            )

        repository = self.format_repository(default_repository, {})
        artifact_names = ("/".join([repository, artifact.name]),)

        registry_addresses = _publish_registry_addresses(self, registries)
        if not registry_addresses:
            return artifact_names

        return tuple(
            "/".join([registry_address, package_name])
            for package_name in artifact_names
            for registry_address in registry_addresses
        )


def _publish_registry_addresses(
    field_set: HelmPublishFieldSet, registries: HelmRegistries
) -> tuple[str, ...]:
    registries_options = tuple(registries.get(*(field_set.registries.value or [])))
    return tuple([registry.address for registry in registries_options])


@rule(desc="Prepare to push Helm chart to OCI registries", level=LogLevel.DEBUG)
async def push_helm_chart(
    request: PublishHelmChartRequest,
    helm: HelmBinary,
    helm_options: HelmSubsystem,
) -> PublishProcesses:
    registries = helm_options.registries()
    built_artifacts = [
        (pkg, cast(BuiltHelmArtifact, artifact))
        for pkg in request.packages
        for artifact in pkg.artifacts
    ]
    package_refs = tuple(
        chain.from_iterable(
            request.field_set.publish_refs(artifact, helm_options.default_repository, registries)
            for _, artifact in built_artifacts
        )
    )

    if request.field_set.skip_push.value:
        return PublishProcesses(
            [
                PublishPackages(
                    names=package_refs,
                    description=f"(by `{request.field_set.skip_push.alias}` on {request.field_set.address})",
                )
            ]
        )

    registry_addresses = _publish_registry_addresses(request.field_set, registries)
    if not registry_addresses:
        return PublishProcesses(
            [
                PublishPackages(
                    names=package_refs,
                    description=f"(by missing `{request.field_set.registries.alias}` on {request.field_set.address})",
                )
            ]
        )

    repository = request.field_set.repository.value or helm_options.default_repository
    processes = [
        helm.push(
            chart=artifact.metadata.name,
            version=artifact.metadata.version,
            path=artifact.relpath,
            digest=pkg.digest,
            oci_registry=f"{registry_address}/{repository}",
        )
        for pkg, artifact in built_artifacts
        if artifact.metadata and artifact.relpath
        for registry_address in registry_addresses
    ]

    interactive_processes = await MultiGet(
        Get(InteractiveProcess, InteractiveProcessRequest(process)) for process in processes
    )

    refs_and_processes = zip(package_refs, interactive_processes)

    return PublishProcesses(
        [
            PublishPackages(names=(package_ref,), process=process)
            for package_ref, process in refs_and_processes
        ]
    )


def rules():
    return [*collect_rules(), *HelmPublishFieldSet.rules()]
