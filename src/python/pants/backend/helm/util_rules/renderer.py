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
from pants.backend.helm.target_types import HelmDeploymentFieldSet
from pants.backend.helm.util_rules import chart, tool
from pants.backend.helm.util_rules.chart import FindHelmDeploymentChart, HelmChart
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_SNAPSHOT,
    CreateDigest,
    Digest,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.meta import frozen_after_init
from pants.util.strutil import softwrap


class HelmDeploymentRendererCmd(Enum):
    """Supported Helm rendering commands, for use when creating a `HelmDeploymentRenderer`."""

    UPGRADE = "upgrade"
    TEMPLATE = "template"


@dataclass(unsafe_hash=True)
@frozen_after_init
class HelmDeploymentRendererRequest:
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
    output_directory: str | None


@dataclass(frozen=True)
class RenderedFiles:
    snapshot: Snapshot


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
    request: HelmDeploymentRendererRequest,
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
            *(("--output-dir", request.output_directory) if request.output_directory else ()),
            *request.extra_argv,
        ],
        extra_env=env,
        extra_immutable_input_digests=immutable_input_digests,
        extra_append_only_caches=append_only_caches,
        description=request.description,
        input_digest=merged_digests,
        output_directories=output_directories,
    )

    return HelmDeploymentRenderer(
        chart=chart, process=process, output_directory=request.output_directory
    )


_HELM_OUTPUT_FILE_MARKER = "# Source: "


@rule
async def run_renderer(renderer: HelmDeploymentRenderer) -> RenderedFiles:
    def file_content(file_name: str, lines: Iterable[str]) -> FileContent:
        content = "\n".join(lines) + "\n"
        if not content.startswith("---"):
            content = "---\n" + content
        return FileContent(file_name, content.encode("utf-8"))

    def parse_renderer_output(result: ProcessResult) -> list[FileContent]:
        rendered_files_contents = result.stdout.decode("utf-8")
        rendered_files: dict[str, list[str]] = {}

        curr_file_name = None
        curr_file_lines: list[str] = []
        for line in rendered_files_contents.splitlines():
            if not line:
                continue

            if line.startswith(_HELM_OUTPUT_FILE_MARKER):
                curr_file_name = line[len(_HELM_OUTPUT_FILE_MARKER) :]

            if not curr_file_name:
                continue

            curr_file_lines = rendered_files.get(curr_file_name, [])
            if not curr_file_lines:
                curr_file_lines = []
                rendered_files[curr_file_name] = curr_file_lines
            curr_file_lines.append(line)

        return [file_content(file_name, lines) for file_name, lines in rendered_files.items()]

    result = await Get(ProcessResult, HelmProcess, renderer.process)

    output_snapshot = EMPTY_SNAPSHOT
    if not renderer.output_directory:
        output_snapshot = await Get(Snapshot, CreateDigest(parse_renderer_output(result)))
    else:
        output_snapshot = await Get(
            Snapshot, RemovePrefix(result.output_digest, renderer.output_directory)
        )

    return RenderedFiles(output_snapshot)


def rules():
    return [*collect_rules(), *chart.rules(), *tool.rules(), *post_renderer.rules()]
