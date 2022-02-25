# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.helm.target_types import HelmChartFieldSet, HelmChartOutputPathField
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartMetadata
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.engine.fs import AddPrefix, Digest, RemovePrefix
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuiltHelmArtifact(BuiltPackageArtifact):
    name: str | None = None
    metadata: HelmChartMetadata | None = None

    @classmethod
    def create(cls, path_to_dir: PurePath, metadata: HelmChartMetadata) -> BuiltHelmArtifact:
        pckg_str = f"{metadata.name}-{metadata.version}"
        path = PurePath(path_to_dir, f"{pckg_str}.tgz")
        return cls(
            metadata=metadata,
            name=pckg_str,
            relpath=str(path),
            extra_log_lines=(f"Built Helm chart artifact: {pckg_str}",),
        )


@dataclass(frozen=True)
class HelmPackageFieldSet(HelmChartFieldSet, PackageFieldSet):
    output_path: HelmChartOutputPathField


@rule(desc="Package Helm chart", level=LogLevel.DEBUG)
async def run_helm_package(field_set: HelmPackageFieldSet, helm: HelmBinary) -> BuiltPackage:
    output_dir = "__output_dir"

    chart = await Get(HelmChart, HelmChartFieldSet, field_set)

    output_destination = PurePath(field_set.output_path.value_or_default(file_ending=None))

    process_result = await Get(
        ProcessResult,
        Process,
        helm.package(
            chart=chart.metadata.name,
            path=chart.path,
            chart_digest=chart.snapshot.digest,
            output_dir=output_dir,
        ),
    )
    output_digest = await Get(Digest, RemovePrefix(process_result.output_digest, output_dir))
    package_digest = await Get(Digest, AddPrefix(output_digest, str(output_destination)))

    return BuiltPackage(
        package_digest,
        (BuiltHelmArtifact.create(output_destination, chart.metadata),),
    )


def rules():
    return [*collect_rules(), UnionRule(PackageFieldSet, HelmPackageFieldSet)]
