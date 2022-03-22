# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.helm.resolve import artifacts
from pants.backend.helm.resolve.artifacts import HelmArtifact
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import HelmArtifactFieldSet
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.fs import CreateDigest, Digest, Directory, RemovePrefix, Snapshot
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchedHelmArtifact:
    address: Address
    snapshot: Snapshot


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
async def fetch_helm_artifacts(
    request: FetchHelmArfifactsRequest, subsystem: HelmSubsystem
) -> FetchedHelmArtifacts:
    remotes = subsystem.remotes()

    download_prefix = "__downloads"
    empty_download_digest = await Get(Digest, CreateDigest([Directory(download_prefix)]))

    artifacts_to_pull = [HelmArtifact.from_field_set(fs) for fs in request.field_sets]
    download_results = await MultiGet(
        Get(
            ProcessResult,
            HelmProcess(
                argv=[
                    "pull",
                    artifact.remote_spec(remotes),
                    "--version",
                    artifact.metadata.version,
                    "--destination",
                    download_prefix,
                    "--untar",
                ],
                input_digest=empty_download_digest,
                description=f"Pulling Helm Chart {artifact.metadata.name} with version {artifact.metadata.version}",
                output_directories=(download_prefix,),
            ),
        )
        for artifact in artifacts_to_pull
    )

    stripped_artifact_snapshots = await MultiGet(
        Get(Snapshot, RemovePrefix(result.output_digest, download_prefix))
        for result in download_results
    )

    fetched_artifacts = [
        FetchedHelmArtifact(address=field_set.address, snapshot=snapshot)
        for field_set, snapshot in zip(request.field_sets, stripped_artifact_snapshots)
    ]
    return FetchedHelmArtifacts(fetched_artifacts)


def rules():
    return [*collect_rules(), *artifacts.rules()]
