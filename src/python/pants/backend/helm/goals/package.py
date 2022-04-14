# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from pants.backend.helm.target_types import HelmChartFieldSet, HelmChartOutputPathField
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.chart_metadata import HelmChartMetadata
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuiltHelmArtifact(BuiltPackageArtifact):
    metadata: HelmChartMetadata | None = None

    @classmethod
    def create(cls, relpath: str, metadata: HelmChartMetadata) -> BuiltHelmArtifact:
        return cls(
            relpath=relpath,
            metadata=metadata,
            extra_log_lines=(f"Built Helm chart artifact: {relpath}",),
        )


@dataclass(frozen=True)
class HelmPackageFieldSet(HelmChartFieldSet, PackageFieldSet):
    output_path: HelmChartOutputPathField


@rule(desc="Package Helm chart", level=LogLevel.DEBUG)
async def run_helm_package(field_set: HelmPackageFieldSet) -> BuiltPackage:
    result_dir = "__out"

    chart, result_digest = await MultiGet(
        Get(HelmChart, HelmChartRequest(field_set)),
        Get(Digest, CreateDigest([Directory(result_dir)])),
    )

    input_digest = await Get(Digest, MergeDigests([chart.snapshot.digest, result_digest]))
    process_output_file = os.path.join(result_dir, f"{chart.metadata.artifact_name}.tgz")

    process_result = await Get(
        ProcessResult,
        HelmProcess(
            argv=["package", chart.path, "-d", result_dir],
            input_digest=input_digest,
            output_files=(process_output_file,),
            description=f"Packaging Helm chart: {field_set.address.spec_path}",
        ),
    )

    stripped_output_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, result_dir)
    )

    final_snapshot = await Get(
        Snapshot,
        AddPrefix(stripped_output_digest, field_set.output_path.value_or_default(file_ending=None)),
    )
    return BuiltPackage(
        final_snapshot.digest,
        artifacts=tuple(
            BuiltHelmArtifact.create(file, chart.metadata) for file in final_snapshot.files
        ),
    )


def rules():
    return [*collect_rules(), UnionRule(PackageFieldSet, HelmPackageFieldSet)]
