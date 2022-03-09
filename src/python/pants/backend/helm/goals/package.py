from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath

from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.engine.fs import AddPrefix, Digest, RemovePrefix, CreateDigest, Directory, MergeDigests
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule, MultiGet
from pants.engine.target import WrappedTarget
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.backend.helm.util_rules.chart import HelmChartMetadata, HelmChartRequest, HelmChart
from pants.backend.helm.target_types import HelmChartFieldSet, HelmChartOutputPathField
from pants.backend.helm.util_rules.tool import HelmProcess

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
async def run_helm_package(field_set: HelmPackageFieldSet) -> BuiltPackage:
  output_dir = "__output_dir"

  chart, output_digest = await MultiGet(
    Get(HelmChart, HelmChartRequest(field_set)),
    Get(Digest, CreateDigest([Directory(output_dir)]))
  )

  input_digest = await Get(Digest, MergeDigests([chart.snapshot.digest, output_digest]))

  process_result = await Get(
    ProcessResult,
    HelmProcess(
      argv=["package", chart.path],
      input_digest=input_digest,
      output_directories=(output_dir,),
      description=f"Packaging Helm chart: {chart.metadata.name}"
    )
  )

  chart_dest_path = PurePath(field_set.output_path.value_or_default(file_ending=None))
  stripped_output_digest = await Get(Digest, RemovePrefix(process_result.output_digest, output_dir))
  dest_digest = await Get(Digest, AddPrefix(stripped_output_digest, str(chart_dest_path)))

  return BuiltPackage(
    dest_digest,
    (BuiltHelmArtifact.create(chart_dest_path, chart.metadata),)
  )


def rules():
  return collect_rules()