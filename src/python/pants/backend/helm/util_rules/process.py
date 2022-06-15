# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from itertools import chain
from pathlib import PurePath
from typing import Iterable, Mapping

from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.engine import process
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_SNAPSHOT,
    CreateDigest,
    Digest,
    Directory,
    MergeDigests,
    Snapshot,
)
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass(unsafe_hash=True)
class HelmProcess:
    """Helper process class used to invoke Helm on a given `input_digest`."""

    argv: tuple[str, ...]
    input_digest: Digest
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    extra_env: FrozenDict[str, str]
    extra_immutable_input_digests: FrozenDict[str, Digest]
    extra_append_only_caches: FrozenDict[str, str]
    cache_scope: ProcessCacheScope | None
    output_directories: tuple[str, ...]
    output_files: tuple[str, ...]
    working_directory: str | None

    def __init__(
        self,
        argv: Iterable[str],
        *,
        input_digest: Digest,
        description: str,
        level: LogLevel = LogLevel.INFO,
        output_directories: Iterable[str] | None = None,
        output_files: Iterable[str] | None = None,
        extra_env: Mapping[str, str] | None = None,
        extra_immutable_input_digests: Mapping[str, Digest] | None = None,
        extra_append_only_caches: Mapping[str, str] | None = None,
        cache_scope: ProcessCacheScope | None = None,
        working_directory: str | None = None,
    ):
        self.argv = tuple(argv)
        self.input_digest = input_digest
        self.description = description
        self.level = level
        self.output_directories = tuple(output_directories or ())
        self.output_files = tuple(output_files or ())
        self.extra_env = FrozenDict(extra_env or {})
        self.extra_immutable_input_digests = FrozenDict(extra_immutable_input_digests or {})
        self.extra_append_only_caches = FrozenDict(extra_append_only_caches or {})
        self.cache_scope = cache_scope
        self.working_directory = working_directory


@rule
def helm_process(request: HelmProcess, helm_binary: HelmBinary) -> Process:
    env = {**helm_binary.env, **request.extra_env}

    immutable_input_digests = {
        **helm_binary.immutable_input_digests,
        **request.extra_immutable_input_digests,
    }

    append_only_caches = {**helm_binary.append_only_caches, **request.extra_append_only_caches}

    return Process(
        [helm_binary.path, *request.argv],
        input_digest=request.input_digest,
        immutable_input_digests=immutable_input_digests,
        env=env,
        description=request.description,
        level=request.level,
        append_only_caches=append_only_caches,
        output_directories=request.output_directories,
        output_files=request.output_files,
        cache_scope=request.cache_scope or ProcessCacheScope.SUCCESSFUL,
        working_directory=request.working_directory,
    )


class HelmRenderCmd(Enum):
    """Supported Helm rendering commands, for use when creating a `HelmRenderProcess`."""

    UPGRADE = "upgrade"
    TEMPLATE = "template"


@frozen_after_init
@dataclass(unsafe_hash=True)
class HelmRenderProcess:
    """Common class for Helm processes that renders a Helm chart with some given values."""

    cmd: HelmRenderCmd
    extra_argv: tuple[str, ...]
    extra_env: FrozenDict[str, str]
    extra_immutable_input_digests: FrozenDict[str, Digest]
    extra_append_only_caches: FrozenDict[str, str]
    level: LogLevel
    cache_scope: ProcessCacheScope | None
    output_directory: str | None
    working_directory: str | None

    release_name: str
    chart_path: str
    chart_digest: Digest
    values_snapshot: Snapshot
    values: FrozenDict[str, str]
    skip_crds: bool
    no_hooks: bool
    description: str | None = dataclasses.field(compare=False)
    namespace: str | None
    message: str = dataclasses.field(compare=False)

    post_renderer_exe: str | None
    post_renderer_argv: tuple[str, ...]
    post_renderer_digest: Digest

    def __init__(
        self,
        cmd: HelmRenderCmd,
        *,
        chart_path: str,
        chart_digest: Digest,
        release_name: str,
        message: str,
        extra_argv: Iterable[str] | None = None,
        extra_env: Mapping[str, str] | None = None,
        extra_immutable_input_digests: Mapping[str, Digest] | None = None,
        extra_append_only_caches: Mapping[str, str] | None = None,
        level: LogLevel = LogLevel.INFO,
        cache_scope: ProcessCacheScope | None = None,
        working_directory: str | None = None,
        description: str | None = None,
        namespace: str | None = None,
        skip_crds: bool = False,
        no_hooks: bool = False,
        values_snapshot: Snapshot = EMPTY_SNAPSHOT,
        values: Mapping[str, str] | None = None,
        output_directory: str | None = None,
        post_renderer_exe: str | None = None,
        post_renderer_argv: Iterable[str] | None = None,
        post_renderer_digest: Digest = EMPTY_DIGEST,
    ) -> None:
        self.cmd = cmd
        self.extra_argv = tuple(extra_argv or ())
        self.extra_env = FrozenDict(extra_env or {})
        self.extra_immutable_input_digests = FrozenDict(extra_immutable_input_digests or {})
        self.extra_append_only_caches = FrozenDict(extra_append_only_caches or {})
        self.level = level
        self.cache_scope = cache_scope
        self.working_directory = working_directory
        self.release_name = release_name
        self.chart_path = chart_path
        self.chart_digest = chart_digest
        self.description = description
        self.namespace = namespace
        self.skip_crds = skip_crds
        self.no_hooks = no_hooks
        self.values_snapshot = values_snapshot
        self.values = FrozenDict(values or {})
        self.message = message
        self.output_directory = output_directory
        self.post_renderer_exe = post_renderer_exe
        self.post_renderer_argv = tuple(post_renderer_argv or ())
        self.post_renderer_digest = post_renderer_digest


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
async def helm_render_process(request: HelmRenderProcess) -> Process:
    output_digest = EMPTY_DIGEST
    if request.output_directory:
        output_digest = await Get(Digest, CreateDigest([Directory(request.output_directory)]))

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                request.chart_digest,
                request.values_snapshot.digest,
                request.post_renderer_digest,
                output_digest,
            ]
        ),
    )

    output_directories = [request.output_directory] if request.output_directory else None

    # Ordering the value file names needs to be consistent so overrides are respected
    sorted_value_files = _sort_value_file_names_for_evaluation(request.values_snapshot.files)
    proccess = HelmProcess(
        argv=[
            request.cmd.value,
            request.release_name,
            request.chart_path,
            *(("--description", f'"{request.description}"') if request.description else ()),
            *(("--namespace", request.namespace) if request.namespace else ()),
            *(("--skip-crds",) if request.skip_crds else ()),
            *(("--no-hooks",) if request.no_hooks else ()),
            *(("--values", ",".join(sorted_value_files)) if sorted_value_files else ()),
            *chain.from_iterable(
                [("--set", f'{key}="{value}"') for key, value in request.values.items()]
            ),
            *(("--post-renderer", request.post_renderer_exe) if request.post_renderer_exe else ()),
            *chain.from_iterable(
                [("--post-renderer-args", arg) for arg in request.post_renderer_argv]
            ),
            *request.extra_argv,
        ],
        input_digest=input_digest,
        description=request.message,
        level=request.level,
        extra_env=request.extra_env,
        extra_immutable_input_digests=request.extra_immutable_input_digests,
        extra_append_only_caches=request.extra_append_only_caches,
        output_directories=output_directories,
        cache_scope=request.cache_scope,
    )
    return await Get(Process, HelmProcess, proccess)


def rules():
    return [*collect_rules(), *tool.rules(), *process.rules()]
