# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from itertools import chain
from pathlib import PurePath
from typing import Any, Iterable, Mapping

from pants.backend.helm.subsystems import post_renderer
from pants.backend.helm.subsystems.post_renderer import HelmPostRendererRunnable
from pants.backend.helm.target_types import HelmDeploymentFieldSet, HelmDeploymentSourcesField
from pants.backend.helm.util_rules import chart, tool
from pants.backend.helm.util_rules.chart import FindHelmDeploymentChart, HelmChart
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
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
from pants.engine.internals.native_engine import FileDigest
from pants.engine.process import (
    InteractiveProcess,
    InteractiveProcessRequest,
    Process,
    ProcessResult,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import pluralize, softwrap

logger = logging.getLogger(__name__)


class HelmDeploymentRendererCmd(Enum):
    """Supported Helm rendering commands, for use when creating a `HelmDeploymentRenderer`."""

    UPGRADE = "upgrade"
    TEMPLATE = "template"


@dataclass(unsafe_hash=True)
@frozen_after_init
class HelmDeploymentRendererRequest(EngineAwareParameter):
    field_set: HelmDeploymentFieldSet

    cmd: HelmDeploymentRendererCmd
    description: str = dataclasses.field(compare=False)
    extra_argv: tuple[str, ...]
    post_renderer: HelmPostRendererRunnable | None

    def __init__(
        self,
        field_set: HelmDeploymentFieldSet,
        *,
        cmd: HelmDeploymentRendererCmd,
        description: str,
        extra_argv: Iterable[str] | None = None,
        post_renderer: HelmPostRendererRunnable | None = None,
    ) -> None:
        self.field_set = field_set
        self.cmd = cmd
        self.description = description
        self.extra_argv = tuple(extra_argv or ())
        self.post_renderer = post_renderer

    def debug_hint(self) -> str | None:
        return self.field_set.address.spec

    def metadata(self) -> dict[str, Any] | None:
        return {
            "cmd": self.cmd.value,
            "address": self.field_set.address,
            "description": self.description,
            "extra_argv": self.extra_argv,
            "post_renderer": True if self.post_renderer else False,
        }


@dataclass(frozen=True)
class HelmDeploymentRenderer(EngineAwareParameter, EngineAwareReturnType):
    address: Address
    chart: HelmChart
    process: HelmProcess
    post_renderer: bool
    output_directory: str | None

    def debug_hint(self) -> str | None:
        return self.address.spec

    def level(self) -> LogLevel | None:
        return LogLevel.DEBUG

    def message(self) -> str | None:
        msg = softwrap(
            f"""
            Built renderer for {self.address} using chart {self.chart.address}
            with{'out' if not self.post_renderer else ''} a post-renderer stage
            """
        )
        if self.output_directory:
            msg += f" and output directory: {self.output_directory}."
        else:
            msg += " and output to stdout."
        return msg

    def metadata(self) -> dict[str, Any] | None:
        return {
            "chart": self.chart.address,
            "helm_argv": self.process.argv,
            "post_renderer": self.post_renderer,
            "output_directory": self.output_directory,
        }


@dataclass(frozen=True)
class RenderedFiles(EngineAwareReturnType):
    address: Address
    chart: HelmChart
    snapshot: Snapshot

    def level(self) -> LogLevel | None:
        return LogLevel.DEBUG

    def message(self) -> str | None:
        return softwrap(
            f"""
            Generated {pluralize(len(self.snapshot.files), 'file')} from deployment {self.address}
            using chart {self.chart}.
            """
        )

    def artifacts(self) -> dict[str, FileDigest | Snapshot] | None:
        return {"content": self.snapshot}

    def metadata(self) -> dict[str, Any] | None:
        return {"deployment": self.address, "chart": self.chart.address}


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


@rule(desc="Prepare Helm deployment renderer", level=LogLevel.DEBUG)
async def setup_render_helm_deployment_process(
    request: HelmDeploymentRendererRequest,
) -> HelmDeploymentRenderer:
    chart, value_files = await MultiGet(
        Get(HelmChart, FindHelmDeploymentChart(request.field_set)),
        Get(
            StrippedSourceFiles,
            SourceFilesRequest(
                sources_fields=[request.field_set.sources],
                for_sources_types=[HelmDeploymentSourcesField],
                enable_codegen=True,
            ),
        ),
    )

    logger.debug(f"Using Helm chart {chart.address} in deployment {request.field_set.address}.")

    output_dir = None
    output_digest = EMPTY_DIGEST
    output_directories = None
    if not request.post_renderer:
        output_dir = "__out"
        output_digest = await Get(Digest, CreateDigest([Directory(output_dir)]))
        output_directories = [output_dir]

    # Ordering the value file names needs to be consistent so overrides are respected.
    sorted_value_files = _sort_value_file_names_for_evaluation(value_files.snapshot.files)

    # Digests to be used as an input into the renderer process.
    input_digests = [
        chart.snapshot.digest,
        value_files.snapshot.digest,
        output_digest,
    ]

    # Additional process values in case a post_renderer has been requested.
    env: Mapping[str, str] = {}
    immutable_input_digests: Mapping[str, Digest] = {}
    append_only_caches: Mapping[str, str] = {}
    if request.post_renderer:
        logger.debug(f"Using post-renderer stage in deployment {request.field_set.address}")
        input_digests.append(request.post_renderer.digest)
        env = request.post_renderer.env
        immutable_input_digests = request.post_renderer.immutable_input_digests
        append_only_caches = request.post_renderer.append_only_caches

    merged_digests = await Get(Digest, MergeDigests(input_digests))

    release_name = request.field_set.release_name.value or request.field_set.address.target_name
    inline_values = request.field_set.values.value

    def maybe_escape_string_value(value: str) -> str:
        if re.findall("\\s+", value):
            return f'"{value}"'
        return value

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
            *(("--create-namespace",) if request.field_set.create_namespace.value else ()),
            *(("--skip-crds",) if request.field_set.skip_crds.value else ()),
            *(("--no-hooks",) if request.field_set.no_hooks.value else ()),
            *(("--output-dir", output_dir) if output_dir else ()),
            *(
                ("--post-renderer", os.path.join(".", request.post_renderer.exe))
                if request.post_renderer
                else ()
            ),
            *(("--values", ",".join(sorted_value_files)) if sorted_value_files else ()),
            *chain.from_iterable(
                (
                    ("--set", f"{key}={maybe_escape_string_value(value)}")
                    for key, value in inline_values.items()
                )
                if inline_values
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

    return HelmDeploymentRenderer(
        address=request.field_set.address,
        chart=chart,
        process=process,
        output_directory=output_dir,
        post_renderer=True if request.post_renderer else False,
    )


_YAML_FILE_SEPARATOR = "---"
_HELM_OUTPUT_FILE_MARKER = "# Source: "


@rule(desc="Run Helm deployment renderer", level=LogLevel.DEBUG)
async def run_renderer(renderer: HelmDeploymentRenderer) -> RenderedFiles:
    def file_content(file_name: str, lines: Iterable[str]) -> FileContent:
        sanitised_lines = list(lines)
        if sanitised_lines[len(sanitised_lines) - 1] == _YAML_FILE_SEPARATOR:
            sanitised_lines = sanitised_lines[:-1]
        if sanitised_lines[0] != _YAML_FILE_SEPARATOR:
            sanitised_lines = [_YAML_FILE_SEPARATOR, *sanitised_lines]

        content = "\n".join(sanitised_lines) + "\n"
        return FileContent(file_name, content.encode("utf-8"))

    def parse_renderer_output(result: ProcessResult) -> list[FileContent]:
        rendered_files_contents = result.stdout.decode("utf-8")
        rendered_files: dict[str, list[str]] = defaultdict(list)

        curr_file_name = None
        for line in rendered_files_contents.splitlines():
            if not line:
                continue

            if line.startswith(_HELM_OUTPUT_FILE_MARKER):
                curr_file_name = line[len(_HELM_OUTPUT_FILE_MARKER) :]

            if not curr_file_name:
                continue

            rendered_files[curr_file_name].append(line)

        return [file_content(file_name, lines) for file_name, lines in rendered_files.items()]

    logger.debug(f"Running Helm renderer process for deployment {renderer.address}")
    result = await Get(ProcessResult, HelmProcess, renderer.process)

    output_snapshot = EMPTY_SNAPSHOT
    if not renderer.output_directory:
        logger.debug(
            f"Parsing Helm renderer files from the process' output of deployment {renderer.address}."
        )
        output_snapshot = await Get(Snapshot, CreateDigest(parse_renderer_output(result)))
    else:
        logger.debug(
            f"Obtaining Helm renderer files from the process' output directory of deployment {renderer.address}."
        )
        output_snapshot = await Get(
            Snapshot, RemovePrefix(result.output_digest, renderer.output_directory)
        )

    return RenderedFiles(address=renderer.address, chart=renderer.chart, snapshot=output_snapshot)


@rule
async def helm_renderer_as_interactive_process(
    renderer: HelmDeploymentRenderer,
) -> InteractiveProcess:
    process = await Get(Process, HelmProcess, renderer.process)
    return await Get(InteractiveProcess, InteractiveProcessRequest(process))


def rules():
    return [*collect_rules(), *chart.rules(), *tool.rules(), *post_renderer.rules()]
