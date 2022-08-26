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
from typing import Any, Iterable, Mapping

from pants.backend.helm.subsystems import post_renderer
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.subsystems.post_renderer import HelmPostRenderer
from pants.backend.helm.target_types import HelmDeploymentFieldSet, HelmDeploymentSourcesField
from pants.backend.helm.util_rules import chart, tool
from pants.backend.helm.util_rules.chart import FindHelmDeploymentChart, HelmChart
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.backend.helm.value_interpolation import HelmEnvironmentInterpolationValue
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_SNAPSHOT,
    CreateDigest,
    Digest,
    DigestSubset,
    Directory,
    FileContent,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.native_engine import FileDigest
from pants.engine.process import InteractiveProcess, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule, rule_helper
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import pluralize, softwrap
from pants.util.value_interpolation import InterpolationContext, InterpolationValue

logger = logging.getLogger(__name__)


class HelmDeploymentCmd(Enum):
    """Supported Helm rendering commands, for use when creating a `HelmDeploymentRenderer`."""

    UPGRADE = "upgrade"
    RENDER = "template"


@dataclass(unsafe_hash=True)
@frozen_after_init
class HelmDeploymentRequest(EngineAwareParameter):
    field_set: HelmDeploymentFieldSet

    cmd: HelmDeploymentCmd
    description: str = dataclasses.field(compare=False)
    extra_argv: tuple[str, ...]
    post_renderer: HelmPostRenderer | None

    def __init__(
        self,
        field_set: HelmDeploymentFieldSet,
        *,
        cmd: HelmDeploymentCmd,
        description: str,
        extra_argv: Iterable[str] | None = None,
        post_renderer: HelmPostRenderer | None = None,
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
            "post_renderer": self.post_renderer,
        }


@dataclass(frozen=True)
class _HelmDeploymentProcessWrapper(EngineAwareParameter, EngineAwareReturnType):
    """Intermediate representation of a `HelmProcess` that will produce a fully rendered set of
    manifests from a given chart.

    The encapsulated `process` will be side-effecting dependening on the `cmd` that was originally requested.

    This is meant to only be used internally by this module.
    """

    chart: HelmChart
    cmd: HelmDeploymentCmd
    process: HelmProcess
    address: Address
    output_directory: str | None

    @property
    def is_side_effect(self) -> bool:
        return self.cmd != HelmDeploymentCmd.RENDER

    @property
    def uses_post_renderer(self) -> bool:
        if self.output_directory:
            return False
        return True

    def debug_hint(self) -> str | None:
        return self.address.spec

    def level(self) -> LogLevel | None:
        return LogLevel.DEBUG

    def message(self) -> str | None:
        msg = softwrap(
            f"""
            Built deployment process for {self.address} using chart {self.chart.address}
            with{'out' if not self.output_directory else ''} a post-renderer stage
            """
        )
        if self.output_directory:
            msg += f" and output directory: {self.output_directory}."
        else:
            msg += " and output to stdout."
        return msg

    def metadata(self) -> dict[str, Any] | None:
        return {
            "address": self.address,
            "chart": self.chart,
            "process": self.process,
            "output_directory": self.output_directory,
        }


@dataclass(frozen=True)
class RenderedHelmFiles(EngineAwareReturnType):
    address: Address
    chart: HelmChart
    snapshot: Snapshot
    post_processed: bool

    def level(self) -> LogLevel | None:
        return LogLevel.DEBUG

    def message(self) -> str | None:
        return softwrap(
            f"""
            Generated {pluralize(len(self.snapshot.files), 'file')} from deployment {self.address}
            using chart {self.chart.address}.
            """
        )

    def artifacts(self) -> dict[str, FileDigest | Snapshot] | None:
        return {"content": self.snapshot}

    def metadata(self) -> dict[str, Any] | None:
        return {"address": self.address, "chart": self.chart, "post_processed": self.post_processed}


@rule_helper
async def _build_interpolation_context(helm_subsystem: HelmSubsystem) -> InterpolationContext:
    interpolation_context: dict[str, dict[str, str] | InterpolationValue] = {}

    env = await Get(Environment, EnvironmentRequest(helm_subsystem.extra_env_vars))
    interpolation_context["env"] = HelmEnvironmentInterpolationValue(env)

    return InterpolationContext.from_dict(interpolation_context)


@rule_helper
async def _sort_value_file_names_for_evaluation(
    address: Address,
    *,
    sources_field: HelmDeploymentSourcesField,
    value_files_snapshot: Snapshot,
    prefix: str,
) -> list[str]:
    """Sorts the list of files in `value_files_snapshot` alphabetically but grouping them in the
    order in which they have been given in the `sources_field` field glob patterns."""

    base_path = address.spec_path
    result: list[str] = []

    if not sources_field.value:
        result = list(value_files_snapshot.files)
        result.sort()
    else:
        # Break the list of filenames in subsets that follow the order given in the `sources` field
        subset_snapshots = await MultiGet(
            Get(
                Snapshot,
                DigestSubset(
                    value_files_snapshot.digest, PathGlobs([os.path.join(base_path, glob_pattern)])
                ),
            )
            for glob_pattern in sources_field.globs
        )
        sources_subsets = [set(snapshot.files) for snapshot in subset_snapshots]

        def minimise_and_sort_subset(input_subset: set[str]) -> list[str]:
            result: set[str] = input_subset
            for subset in sources_subsets:
                if subset == input_subset:
                    continue

                if result.issuperset(subset):
                    result = result.difference(subset)

            result_as_list = list(result)
            result_as_list.sort()
            return result_as_list

        result = list(
            chain.from_iterable([minimise_and_sort_subset(subset) for subset in sources_subsets])
        )

    logger.debug(
        softwrap(
            f"""Value files for {address} would be evaluated using the following order:

            {', '.join(result)}
            """
        )
    )

    return [os.path.join(prefix, filename) for filename in result]


@rule(desc="Prepare Helm deployment renderer")
async def setup_render_helm_deployment_process(
    request: HelmDeploymentRequest, helm_subsystem: HelmSubsystem
) -> _HelmDeploymentProcessWrapper:
    value_files_prefix = "__values"
    chart, value_files = await MultiGet(
        Get(HelmChart, FindHelmDeploymentChart(request.field_set)),
        Get(
            SourceFiles,
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

    # Sort the list of file names following a consistent ordering
    sorted_value_files = await _sort_value_file_names_for_evaluation(
        request.field_set.address,
        sources_field=request.field_set.sources,
        value_files_snapshot=value_files.snapshot,
        prefix=value_files_prefix,
    )

    # Digests to be used as an input into the renderer process.
    input_digests = [output_digest]

    # Additional process values in case a post_renderer has been requested.
    env: Mapping[str, str] = {}
    immutable_input_digests: dict[str, Digest] = {
        **chart.immutable_input_digests,
        value_files_prefix: value_files.snapshot.digest,
    }
    append_only_caches: Mapping[str, str] = {}
    if request.post_renderer:
        logger.debug(f"Using post-renderer stage in deployment {request.field_set.address}")
        input_digests.append(request.post_renderer.digest)
        env = request.post_renderer.env
        immutable_input_digests.update(request.post_renderer.immutable_input_digests)
        append_only_caches = request.post_renderer.append_only_caches

    merged_digests = await Get(Digest, MergeDigests(input_digests))

    interpolation_context = await _build_interpolation_context(helm_subsystem)

    release_name = (
        request.field_set.release_name.value
        or request.field_set.address.target_name.replace("_", "-")
    )
    inline_values = request.field_set.format_values(
        interpolation_context, ignore_missing=request.cmd == HelmDeploymentCmd.RENDER
    )

    def maybe_escape_string_value(value: str) -> str:
        if re.findall("\\s+", value):
            return f'"{value}"'
        return value

    process = HelmProcess(
        argv=[
            request.cmd.value,
            release_name,
            chart.name,
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

    return _HelmDeploymentProcessWrapper(
        cmd=request.cmd,
        chart=chart,
        process=process,
        address=request.field_set.address,
        output_directory=output_dir,
    )


_YAML_FILE_SEPARATOR = "---"
_HELM_OUTPUT_FILE_MARKER = "# Source: "


@rule(desc="Render Helm deployment", level=LogLevel.DEBUG)
async def run_renderer(process_wrapper: _HelmDeploymentProcessWrapper) -> RenderedHelmFiles:
    assert not process_wrapper.is_side_effect

    def file_content(file_name: str, lines: Iterable[str]) -> FileContent:
        sanitised_lines = list(lines)
        if len(sanitised_lines) == 0:
            return FileContent(file_name, b"")
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

    logger.debug(f"Rendering Helm files for {process_wrapper.address}")
    result = await Get(ProcessResult, HelmProcess, process_wrapper.process)

    output_snapshot = EMPTY_SNAPSHOT
    if not process_wrapper.output_directory:
        logger.debug(
            f"Parsing Helm rendered files from the process' output of {process_wrapper.address}."
        )
        output_snapshot = await Get(Snapshot, CreateDigest(parse_renderer_output(result)))
    else:
        logger.debug(
            f"Obtaining Helm rendered files from the process' output directory of {process_wrapper.address}."
        )
        output_snapshot = await Get(
            Snapshot, RemovePrefix(result.output_digest, process_wrapper.output_directory)
        )

    return RenderedHelmFiles(
        address=process_wrapper.address,
        chart=process_wrapper.chart,
        snapshot=output_snapshot,
        post_processed=process_wrapper.uses_post_renderer,
    )


@rule
async def materialize_deployment_process_wrapper_into_interactive_process(
    process_wrapper: _HelmDeploymentProcessWrapper,
) -> InteractiveProcess:
    assert process_wrapper.is_side_effect

    process = await Get(Process, HelmProcess, process_wrapper.process)
    return InteractiveProcess.from_process(process)


def rules():
    return [*collect_rules(), *chart.rules(), *tool.rules(), *post_renderer.rules()]
