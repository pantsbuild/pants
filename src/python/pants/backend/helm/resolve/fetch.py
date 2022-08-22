# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from pants.backend.helm.resolve import artifacts
from pants.backend.helm.resolve.artifacts import HelmArtifact, ResolvedHelmArtifact
from pants.backend.helm.target_types import HelmArtifactFieldSet, HelmArtifactTarget
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestSubset,
    Directory,
    FileDigest,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class InvalidHelmArtifactTarget(Exception):
    def __init__(self, target: Target) -> None:
        super().__init__(
            softwrap(
                f"""
                Can not fetch a Helm artifact for a `{target.alias}` target.

                Helm artifacts are defined using target `{HelmArtifactTarget.alias}`.
                """
            )
        )


@dataclass(frozen=True)
class FetchHelmArtifactRequest(EngineAwareParameter):
    field_set: HelmArtifactFieldSet
    description_of_origin: str

    @classmethod
    def from_target(cls, target: Target, *, description_of_origin: str) -> FetchHelmArtifactRequest:
        if not HelmArtifactFieldSet.is_applicable(target):
            raise InvalidHelmArtifactTarget(target)

        return cls(
            field_set=HelmArtifactFieldSet.create(target),
            description_of_origin=description_of_origin,
        )

    def debug_hint(self) -> str | None:
        return f"{self.field_set.address} from {self.description_of_origin}"

    def metadata(self) -> dict[str, Any] | None:
        return {
            "address": self.field_set.address.spec,
            "description_of_origin": self.description_of_origin,
        }


@dataclass(frozen=True)
class FetchedHelmArtifact(EngineAwareReturnType):
    artifact: ResolvedHelmArtifact
    snapshot: Snapshot

    @property
    def address(self) -> Address:
        return self.artifact.address

    def level(self) -> LogLevel | None:
        return LogLevel.DEBUG

    def message(self) -> str | None:
        return softwrap(
            f"""
            Fetched Helm artifact '{self.artifact.name}' with version {self.artifact.version}
            using URL: {self.artifact.chart_url}
            """
        )

    def metadata(self) -> dict[str, Any] | None:
        return {"artifact": self.artifact}

    def artifacts(self) -> dict[str, FileDigest | Snapshot] | None:
        return {"snapshot": self.snapshot}


@rule(desc="Fetch Helm artifact", level=LogLevel.DEBUG)
async def fetch_helm_artifact(request: FetchHelmArtifactRequest) -> FetchedHelmArtifact:
    download_prefix = "__downloads"

    empty_download_digest, resolved_artifact = await MultiGet(
        Get(Digest, CreateDigest([Directory(download_prefix)])),
        Get(ResolvedHelmArtifact, HelmArtifact, HelmArtifact.from_field_set(request.field_set)),
    )

    download_result = await Get(
        ProcessResult,
        HelmProcess(
            argv=[
                "pull",
                resolved_artifact.name,
                "--repo",
                resolved_artifact.location_url,
                "--version",
                resolved_artifact.version,
                "--destination",
                download_prefix,
                "--untar",
            ],
            input_digest=empty_download_digest,
            description=f"Pulling Helm Chart '{resolved_artifact.name}' with version {resolved_artifact.version}.",
            output_directories=(download_prefix,),
            level=LogLevel.DEBUG,
        ),
    )

    raw_output_digest = await Get(
        Digest, RemovePrefix(download_result.output_digest, download_prefix)
    )

    # The download result will come with a tarball alongside the unzipped sources, pick the chart sources only.
    artifact_sources_digest = await Get(
        Digest,
        DigestSubset(raw_output_digest, PathGlobs([os.path.join(resolved_artifact.name, "**")])),
    )
    artifact_snapshot = await Get(
        Snapshot, RemovePrefix(artifact_sources_digest, resolved_artifact.name)
    )

    return FetchedHelmArtifact(artifact=resolved_artifact, snapshot=artifact_snapshot)


def rules():
    return [*collect_rules(), *artifacts.rules(), *tool.rules()]
