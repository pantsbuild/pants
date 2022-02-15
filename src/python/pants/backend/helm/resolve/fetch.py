# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.helm.resolve.artifacts import HelmArtifact
from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import (
    HelmArtifactArtifactField,
    HelmArtifactFieldSet,
    HelmArtifactRegistryField,
    HelmArtifactRepositoryField,
    HelmArtifactVersionField,
)
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.fs import CreateDigest, Digest, Directory, RemovePrefix, Snapshot
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import bullet_list

logger = logging.getLogger(__name__)


class UnknownRegistryError(ValueError):
    pass


class InvalidHelmArtifactError(ValueError):
    pass


class InvalidRegistryError(ValueError):
    pass


class InvalidRepositoryError(ValueError):
    pass


class FailedFetchingHelmArtifactsException(Exception):
    pass


@dataclass(frozen=True)
class FetchedHelmArtifact:
    address: Address
    snapshot: Snapshot


@dataclass(frozen=True)
class FallibleFetchedArtifactsResult:
    exit_code: int
    fetched_artifacts: tuple[FetchedHelmArtifact, ...]
    description: str | None = None


class FetchedHelmArtifacts(Collection[FetchedHelmArtifact]):
    pass


@frozen_after_init
@dataclass(unsafe_hash=True)
class FetchHelmArfifactsRequest:
    field_sets: tuple[HelmArtifactFieldSet, ...]

    def __init__(self, field_sets: Iterable[HelmArtifactFieldSet]) -> None:
        self.field_sets = tuple(field_sets)

    @classmethod
    def for_targets(cls, targets: Iterable[Target]) -> FetchHelmArfifactsRequest:
        return cls(
            [
                HelmArtifactFieldSet.create(tgt)
                for tgt in targets
                if HelmArtifactFieldSet.is_applicable(tgt)
            ]
        )


@rule(desc="Fetch third party Helm Chart artifacts", level=LogLevel.DEBUG)
async def fallible_fetch_helm_artifacts(
    request: FetchHelmArfifactsRequest, helm_options: HelmSubsystem, helm: HelmBinary
) -> FallibleFetchedArtifactsResult:
    registries = helm_options.registries()

    output_prefix = "__downloads"
    empty_output_digest = await Get(Digest, CreateDigest([Directory(output_prefix)]))

    def get_repo_for_fs(fs: HelmArtifactFieldSet) -> str:
        registry_value = fs.registry.value
        repository_value = fs.repository.value

        if registry_value:
            try:
                registry = registries.all[registry_value]
            except KeyError:
                raise UnknownRegistryError(
                    f"The registry '{registry_value}' has not been configured. "
                    "Please, add registry configuration to the `[helm].registries` setting in order to support it. "
                    f"Use `{bin_name()} help helm` to get some help on how to configure it."
                )

            if not registry.is_oci:
                raise InvalidRegistryError(
                    f"The registry address '{registry.address}' is invalid. "
                    f"Only OCI registries are allowed in the `{HelmArtifactRegistryField.alias}` field. "
                    f"For classic Helm repositories, use the `{HelmArtifactRepositoryField.alias}` field using an `@` followed by the configured alias of that repository."
                )

            path = repository_value or (helm_options.default_repository if registry.default else "")

            return f"{registry.address}/{path}".rstrip("/")
        elif repository_value:
            if not repository_value.startswith("@"):
                raise InvalidRepositoryError(
                    f"Invalid repository alias reference '{repository_value}'. "
                    "When referencing classic Helm repositories, you must use the `@` symbol before the alias."
                )
            return repository_value.lstrip("@")
        else:
            raise InvalidHelmArtifactError(
                f"Target at address '{fs.address}' needs to specify either `{HelmArtifactRegistryField.alias}`, `{HelmArtifactRepositoryField.alias}` or both."
            )

    def create_process(fs: HelmArtifactFieldSet) -> Process:
        repository_ref = get_repo_for_fs(fs)
        artifact_name = fs.artifact.value
        if not artifact_name:
            raise InvalidHelmArtifactError(
                f"Target at address '{fs.address}' is missing a value for the `{HelmArtifactArtifactField.alias}` field"
            )

        artifact_version = fs.version.value
        if not artifact_version:
            raise InvalidHelmArtifactError(
                f"Target at address '{fs.address}' is missing a value for the `{HelmArtifactVersionField.alias}` field"
            )

        artifact_url = f"{repository_ref}/{artifact_name}"
        return helm.pull(
            artifact_url,
            version=artifact_version,
            dest_dir=output_prefix,
            dest_digest=empty_output_digest,
        )

    results = await MultiGet(
        Get(FallibleProcessResult, Process, create_process(fs)) for fs in request.field_sets
    )
    artifact_snapshots = await MultiGet(
        Get(Snapshot, RemovePrefix(result.output_digest, output_prefix))
        for result in results
        if result.exit_code == 0
    )

    failed_artifacts = [
        f"{HelmArtifact.from_field_set(field_set)}: {result.stderr.decode()}"
        for field_set, result in zip(request.field_sets, results)
        if result.exit_code != 0
    ]
    fetched_artifacts = [
        FetchedHelmArtifact(address=field_set.address, snapshot=snapshot)
        for field_set, snapshot in zip(request.field_sets, artifact_snapshots)
    ]

    if failed_artifacts:
        return FallibleFetchedArtifactsResult(
            exit_code=1,
            fetched_artifacts=tuple(fetched_artifacts),
            description=f"Failed to fetch the following artifacts:\n{bullet_list(failed_artifacts)}",
        )

    return FallibleFetchedArtifactsResult(exit_code=0, fetched_artifacts=tuple(fetched_artifacts))


@rule
async def fetch_helm_artifacts(request: FetchHelmArfifactsRequest) -> FetchedHelmArtifacts:
    fallible_result = await Get(FallibleFetchedArtifactsResult, FetchHelmArfifactsRequest, request)
    if fallible_result.exit_code != 0 and fallible_fetch_helm_artifacts.description:
        raise FailedFetchingHelmArtifactsException(fallible_fetch_helm_artifacts.description)
    return FetchedHelmArtifacts(fallible_result.fetched_artifacts)


def rules():
    return collect_rules()
