# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import Tuple

from pants.backend.python.dependency_inference.module_mapper import module_from_stripped_path
from pants.backend.python.lint.isort.skip_field import SkipIsortField
from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.target_types import PythonDependenciesField, PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, PexResolveInfo, VenvPex, VenvPexProcess
from pants.core.goals.fix import Partitions
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import PartitionerType, Partitions
from pants.core.util_rules.stripped_source_files import StrippedFileName, StrippedFileNameRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import ProcessExecutionFailure, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    FieldSet,
    SourcesPaths,
    SourcesPathsRequest,
    Target,
    Targets,
)
from pants.option.global_options import KeepSandboxes
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class IsortFieldSet(FieldSet):
    required_fields = (PythonSourceField, PythonDependenciesField)

    source: PythonSourceField
    dependencies: PythonDependenciesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipIsortField).value


class IsortRequest(FmtTargetsRequest):
    field_set_type = IsortFieldSet
    tool_subsystem = Isort
    partitioner_type = PartitionerType.CUSTOM


@dataclass(frozen=True)
class IsortPartitionMetadata:
    path_to_firstparty_modules: FrozenDict[str, tuple[str, ...]]

    @property
    def description(self) -> str | None:
        return None


@rule(desc="Partition isort", level=LogLevel.DEBUG)
async def isort_partition(
    request: IsortRequest.PartitionRequest, isort: Isort
) -> Partitions[str, IsortPartitionMetadata]:
    if isort.skip:
        return Partitions()

    all_sources_paths = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(field_set.source)) for field_set in request.field_sets
    )

    metadata = defaultdict(set)
    if isort.firstparty_discovery:
        direct_dependencies = await MultiGet(
            Get(Targets, DependenciesRequest(field_set.dependencies))
            for field_set in request.field_sets
        )
        all_direct_targets = {*itertools.chain.from_iterable(direct_dependencies)}
        stripped_files = await MultiGet(
            Get(
                StrippedFileName,
                StrippedFileNameRequest(
                    target.get(PythonSourceField, default_raw_value="").file_path
                ),
            )
            for target in all_direct_targets
        )
        stripped_file_paths = (PurePath(stripped_file.value) for stripped_file in stripped_files)
        target_to_stripped_file = {
            target: module_from_stripped_path(stripped_path)
            for target, stripped_path in zip(all_direct_targets, stripped_file_paths)
            if stripped_path and stripped_path.name
        }

        for source_paths, direct_deps in zip(all_sources_paths, direct_dependencies):
            for path in source_paths.files:
                metadata[path].update(
                    target_to_stripped_file[target]
                    for target in direct_deps
                    if target in target_to_stripped_file
                )

    return Partitions.single_partition(
        itertools.chain.from_iterable(sources_paths.files for sources_paths in all_sources_paths),
        metadata=IsortPartitionMetadata(
            FrozenDict((path, tuple(sorted(mods))) for path, mods in metadata.items())
        ),
    )


def generate_argv(
    source_files: tuple[str, ...],
    isort: Isort,
    *,
    is_isort5: bool,
    direct_dep_modules: set[str],
) -> Tuple[str, ...]:
    args = [*isort.args]
    if is_isort5 and len(isort.config) == 1:
        explicitly_configured_config_args = [
            arg
            for arg in isort.args
            if (
                arg.startswith("--sp")
                or arg.startswith("--settings-path")
                or arg.startswith("--settings-file")
                or arg.startswith("--settings")
            )
        ]
        # TODO: Deprecate manually setting this option, but wait until we deprecate
        #  `[isort].config` to be a string rather than list[str] option.
        if not explicitly_configured_config_args:
            args.append(f"--settings={isort.config[0]}")
    args.extend(f"-p={mod}" for mod in sorted(direct_dep_modules))
    args.extend(source_files)
    return tuple(args)


@rule(desc="Format with isort", level=LogLevel.DEBUG)
async def isort_fmt(
    request: IsortRequest.Batch[str, IsortPartitionMetadata],
    isort: Isort,
    keep_sandboxes: KeepSandboxes,
) -> FmtResult:
    direct_dep_modules = {
        *itertools.chain.from_iterable(
            request.partition_metadata.path_to_firstparty_modules.get(filepath, ())
            for filepath in request.elements
        )
    }

    isort_pex_get = Get(VenvPex, PexRequest, isort.to_pex_request())
    config_files_get = Get(
        ConfigFiles, ConfigFilesRequest, isort.config_request(request.snapshot.dirs)
    )
    isort_pex, config_files = await MultiGet(isort_pex_get, config_files_get)

    # Isort 5+ changes how config files are handled. Determine which semantics we should use.
    is_isort5 = False
    if isort.config:
        isort_pex_info = await Get(PexResolveInfo, VenvPex, isort_pex)
        isort_info = isort_pex_info.find("isort")
        is_isort5 = isort_info is not None and isort_info.version.major >= 5

    input_digest = await Get(
        Digest, MergeDigests((request.snapshot.digest, config_files.snapshot.digest))
    )

    description = f"Run isort on {pluralize(len(request.files), 'file')}."
    result = await Get(
        ProcessResult,
        VenvPexProcess(
            isort_pex,
            argv=generate_argv(
                request.files, isort, is_isort5=is_isort5, direct_dep_modules=direct_dep_modules
            ),
            input_digest=input_digest,
            output_files=request.files,
            description=description,
            level=LogLevel.DEBUG,
        ),
    )

    if b"Failed to pull configuration information" in result.stderr:
        raise ProcessExecutionFailure(
            -1,
            result.stdout,
            result.stderr,
            description,
            keep_sandboxes=keep_sandboxes,
        )

    return await FmtResult.create(request, result, strip_chroot_path=True)


def rules():
    return [
        *collect_rules(),
        *IsortRequest.rules(),
        *pex.rules(),
    ]
