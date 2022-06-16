# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from enum import Enum
from itertools import chain
from pathlib import PurePath
from typing import Iterable, Mapping

from pants.backend.helm.subsystems import post_renderer
from pants.backend.helm.subsystems.post_renderer import PostRendererLauncherSetup
from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartTarget,
    HelmDeploymentFieldSet,
)
from pants.backend.helm.util_rules import chart, process
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.process import HelmProcess
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    Directory,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, ExplicitlyProvidedDependencies, Targets
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import softwrap


class MissingHelmDeploymentChartError(ValueError):
    def __init__(self, address: Address) -> None:
        super().__init__(
            f"The target '{address}' is missing a dependency on a `{HelmChartTarget.alias}` target."
        )


class TooManyChartDependenciesError(ValueError):
    def __init__(self, address: Address) -> None:
        super().__init__(
            f"The target '{address}' has too many `{HelmChartTarget.alias}` "
            "addresses in its dependencies, it should have only one."
        )


@dataclass(frozen=True)
class FindHelmDeploymentChart:
    field_set: HelmDeploymentFieldSet


@rule
async def get_chart_of_deployment(request: FindHelmDeploymentChart) -> HelmChartRequest:
    explicit_dependencies = await Get(
        ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)
    )
    explicit_targets = await Get(
        Targets,
        Addresses(
            [
                addr
                for addr in explicit_dependencies.includes
                if addr not in explicit_dependencies.ignores
            ]
        ),
    )

    found_charts = [tgt for tgt in explicit_targets if HelmChartFieldSet.is_applicable(tgt)]
    if not found_charts:
        raise MissingHelmDeploymentChartError(request.field_set.address)
    if len(found_charts) > 1:
        raise TooManyChartDependenciesError(request.field_set.address)

    return HelmChartRequest.from_target(found_charts[0])


class HelmDeploymentRendererCmd(Enum):
    """Supported Helm rendering commands, for use when creating a `HelmDeploymentRenderer`."""

    UPGRADE = "upgrade"
    TEMPLATE = "template"


@dataclass(unsafe_hash=True)
@frozen_after_init
class SetupHelmDeploymentRenderer:
    field_set: HelmDeploymentFieldSet

    cmd: HelmDeploymentRendererCmd
    description: str = dataclasses.field(compare=False)
    extra_argv: tuple[str, ...]
    post_renderer: PostRendererLauncherSetup | None
    output_directory: str | None

    def __init__(
        self,
        field_set: HelmDeploymentFieldSet,
        *,
        cmd: HelmDeploymentRendererCmd,
        description: str,
        extra_argv: Iterable[str] | None = None,
        post_renderer: PostRendererLauncherSetup | None = None,
        output_directory: str | None = None,
    ) -> None:
        self.field_set = field_set
        self.cmd = cmd
        self.description = description
        self.extra_argv = tuple(extra_argv or ())
        self.post_renderer = post_renderer
        self.output_directory = output_directory

        if self.post_renderer and self.output_directory:
            raise ValueError(
                softwrap(
                    """
                    Both `post_renderer` and `output_directory` have been set but only one of them
                    is allowed at the same time.

                    Remove either of them to be able to create a valid instance of a `HelmDeploymentRenderer`.
                    """
                )
            )


@dataclass(frozen=True)
class HelmDeploymentRenderer:
    chart: HelmChart
    process: HelmProcess


def _sort_value_file_names_for_evaluation(filenames: Iterable[str]) -> list[str]:
    """Breaks the list of files into two main buckets: overrides and non-overrides, and then sorts
    each of the buckets using a path-based criteria.

    The final list will be composed by the non-overrides bucket followed by the overrides one.
    """

    non_overrides = []
    overrides = []
    paths = [PurePath(filename) for filename in filenames]
    for p in paths:
        if "override" in p.name.lower():
            overrides.append(p)
        else:
            non_overrides.append(p)

    def by_path_length(p: PurePath) -> int:
        if not p.parents:
            return 0
        return len(p.parents)

    non_overrides.sort(key=by_path_length)
    overrides.sort(key=by_path_length)
    return [str(path) for path in [*non_overrides, *overrides]]


@rule
async def setup_render_helm_deployment_process(
    request: SetupHelmDeploymentRenderer,
) -> HelmDeploymentRenderer:
    chart, value_files = await MultiGet(
        Get(HelmChart, FindHelmDeploymentChart(request.field_set)),
        Get(StrippedSourceFiles, SourceFilesRequest([request.field_set.sources])),
    )

    output_digest = EMPTY_DIGEST
    if request.output_directory:
        output_digest = await Get(Digest, CreateDigest([Directory(request.output_directory)]))

    input_digests = [
        chart.snapshot.digest,
        value_files.snapshot.digest,
        output_digest,
    ]

    if request.post_renderer:
        input_digests.append(request.post_renderer.digest)

    merged_digests = await Get(Digest, MergeDigests(input_digests))

    # Ordering the value file names needs to be consistent so overrides are respected
    sorted_value_files = _sort_value_file_names_for_evaluation(value_files.snapshot.files)

    env: Mapping[str, str] = {}
    immutable_input_digests: Mapping[str, Digest] = {}
    append_only_caches: Mapping[str, str] = {}
    if request.post_renderer:
        env = request.post_renderer.env
        immutable_input_digests = request.post_renderer.immutable_input_digests
        append_only_caches = request.post_renderer.append_only_caches

    output_directories = [request.output_directory] if request.output_directory else None

    release_name = request.field_set.release_name.value or request.field_set.address.target_name
    inline_values = request.field_set.values.value
    process = HelmProcess(
        argv=[
            request.cmd.value,
            release_name,
            chart.path,
            *(
                ("--description", f'"{request.field_set.description.value}"')
                if request.field_set.description.value
                else ()
            ),
            *(
                ("--namespace", request.field_set.namespace.value)
                if request.field_set.namespace.value
                else ()
            ),
            *(("--skip-crds",) if request.field_set.skip_crds.value else ()),
            *(("--no-hooks",) if request.field_set.no_hooks.value else ()),
            *(("--values", ",".join(sorted_value_files)) if sorted_value_files else ()),
            *chain.from_iterable(
                (("--set", f'{key}="{value}"') for key, value in inline_values.items())
                if inline_values
                else ()
            ),
            *(
                ("--post-renderer", os.path.join(".", request.post_renderer.exe))
                if request.post_renderer
                else ()
            ),
            *request.extra_argv,
        ],
        extra_env=env,
        extra_immutable_input_digests=immutable_input_digests,
        extra_append_only_caches=append_only_caches,
        description=request.description,
        input_digest=merged_digests,
        output_directories=output_directories,
    )

    return HelmDeploymentRenderer(chart=chart, process=process)


@dataclass(frozen=True)
class RenderHelmDeploymentRequest:
    """Renders a `helm_deployment` target and produces a snapshot containing the rendered
    manifests."""

    field_set: HelmDeploymentFieldSet
    api_versions: tuple[str, ...] = ()
    kube_version: str | None = None


@dataclass(frozen=True)
class RenderedDeployment:
    address: Address
    snapshot: Snapshot


@rule(desc="Render Helm deployment", level=LogLevel.DEBUG)
async def render_helm_deployment(request: RenderHelmDeploymentRequest) -> RenderedDeployment:
    output_dir = "__output"

    renderer = await Get(
        HelmDeploymentRenderer,
        SetupHelmDeploymentRenderer(
            cmd=HelmDeploymentRendererCmd.TEMPLATE,
            field_set=request.field_set,
            description=f"Rendering Helm deployment {request.field_set.address}",
            extra_argv=[
                *(("--kube-version", request.kube_version) if request.kube_version else ()),
                *chain.from_iterable(
                    [("--api-versions", api_version) for api_version in request.api_versions]
                ),
                "--output-dir",
                output_dir,
            ],
            output_directory=output_dir,
        ),
    )
    result = await Get(ProcessResult, HelmProcess, renderer.process)

    output_snapshot = await Get(Snapshot, RemovePrefix(result.output_digest, output_dir))
    return RenderedDeployment(address=request.field_set.address, snapshot=output_snapshot)


def rules():
    return [*collect_rules(), *chart.rules(), *process.rules(), *post_renderer.rules()]
