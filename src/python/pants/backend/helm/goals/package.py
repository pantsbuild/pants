# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.helm.target_types import HelmChartFieldSet, HelmChartOutputPathField
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartMetadata, HelmChartRequest
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.engine.fs import AddPrefix, CreateDigest, Digest, Directory, MergeDigests, RemovePrefix
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuiltHelmArtifact(BuiltPackageArtifact):
    name: str | None = None
    metadata: HelmChartMetadata | None = None

    @classmethod
    def create(cls, path_to_dir: PurePath, chart_metadata: HelmChartMetadata) -> BuiltHelmArtifact:
        path = PurePath(path_to_dir, _helm_artifact_filename(chart_metadata))
        return cls(
            name=chart_metadata.artifact_name,
            metadata=chart_metadata,
            relpath=str(path),
            extra_log_lines=(f"Built Helm chart artifact: {path}",),
        )


def _helm_artifact_filename(chart_metadata: HelmChartMetadata) -> str:
    return f"{chart_metadata.artifact_name}.tgz"


@dataclass(frozen=True)
class HelmPackageFieldSet(HelmChartFieldSet, PackageFieldSet):
    output_path: HelmChartOutputPathField


@rule(desc="Package Helm chart", level=LogLevel.DEBUG)
async def run_helm_package(field_set: HelmPackageFieldSet) -> BuiltPackage:
    output_dir = "__output_dir"

    chart, output_digest = await MultiGet(
        Get(HelmChart, HelmChartRequest(field_set)),
        Get(Digest, CreateDigest([Directory(output_dir)])),
    )

    input_digest = await Get(Digest, MergeDigests([chart.snapshot.digest, output_digest]))

    chart_output_path = PurePath(field_set.output_path.value_or_default(file_ending=None))
    process_output_path = PurePath(output_dir, chart_output_path)
    process_output_file = process_output_path.joinpath(_helm_artifact_filename(chart.metadata))

    process_result = await Get(
        ProcessResult,
        HelmProcess(
            argv=["package", chart.path, "-d", output_dir],
            input_digest=input_digest,
            output_files=(str(process_output_file),),
            description=f"Packaging Helm chart: {chart.metadata.name}",
        ),
    )

    stripped_output_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, output_dir)
    )
    dest_digest = await Get(Digest, AddPrefix(stripped_output_digest, str(chart_output_path)))

    return BuiltPackage(dest_digest, (BuiltHelmArtifact.create(chart_output_path, chart.metadata),))


def rules():
    return collect_rules()
