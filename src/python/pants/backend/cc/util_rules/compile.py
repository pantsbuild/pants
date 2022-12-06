# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.cc.dependency_inference.rules import (
    CCDependencyInferenceFieldSet,
    InferCCDependenciesRequest,
)
from pants.backend.cc.target_types import CC_HEADER_FILE_EXTENSIONS, CCDependenciesField, CCFieldSet
from pants.backend.cc.util_rules.toolchain import CCProcess
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, rule, rule_helper
from pants.engine.target import (
    InferredDependencies,
    SourcesField,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompileCCSourceRequest:
    """A request to compile a single C/C++ source file."""

    field_set: CCFieldSet


@dataclass(frozen=True)
class CompiledCCObject:
    """A compiled C/C++ object file."""

    digest: Digest


@dataclass(frozen=True)
class FallibleCompiledCCObject:
    """A compiled C/C++ object file, which may have failed to compile."""

    name: str
    process_result: FallibleProcessResult


@rule_helper
async def _infer_source_files(field_set: CCFieldSet) -> SourceFiles:
    """Try to determine what this file needs in its digest to compile correctly (i.e. which header
    files)"""

    # TODO: Switching to fieldsets makes this inference request weirder
    inferred_dependencies = await Get(
        InferredDependencies,
        InferCCDependenciesRequest(
            CCDependencyInferenceFieldSet(
                field_set.address, field_set.sources, CCDependenciesField(None, field_set.address)
            )
        ),
    )

    # Convert inferred dependency addresses into targets
    wrapped_targets = await MultiGet(
        Get(
            WrappedTarget,
            WrappedTargetRequest(address, description_of_origin="<cc/util_rules/compile.py>"),
        )
        for address in inferred_dependencies.include
    )

    return await Get(
        SourceFiles,
        SourceFilesRequest(
            [wrapped_target.target.get(SourcesField) for wrapped_target in wrapped_targets]
        ),
    )


def _extract_include_directories(inferred_source_files: SourceFiles) -> list[str]:
    """Extract the include directories from the inferred source files."""

    # Add header include directories to compilation args prefixed with "-I"
    inferred_header_files = [
        file
        for file in inferred_source_files.files
        if PurePath(file).suffix in CC_HEADER_FILE_EXTENSIONS
    ]
    # TODO: This "/inc" is hardcoded - not a robust way to determine which folders should be included here
    return [file.split("/inc")[0] for file in inferred_header_files if "/inc" in file]


@rule(desc="Compile CC source with the current toolchain")
async def compile_cc_source(request: CompileCCSourceRequest) -> FallibleCompiledCCObject:
    """Compile a single C/C++ source file."""

    field_set = request.field_set

    # Gather all required source files and dependencies
    target_source_file = await Get(SourceFiles, SourceFilesRequest([field_set.sources]))

    inferred_source_files = await _infer_source_files(field_set)

    input_digest = await Get(
        Digest,
        MergeDigests((target_source_file.snapshot.digest, inferred_source_files.snapshot.digest)),
    )

    include_directories = _extract_include_directories(inferred_source_files)

    # Generate target compilation args
    target_file = target_source_file.files[0]
    compiled_object_name = f"{target_file}.o"

    argv = []
    for d in include_directories:
        argv += ["-I", f"{d}/include"]
    # TODO: Testing compilation database - clang only
    # argv += ["-MJ", "compile_commands.json", ""]
    # Apply target compile options and defines

    argv += field_set.compile_flags.value or []
    argv += field_set.defines.value or []
    argv += ["-c", target_file, "-o", compiled_object_name]

    compile_result = await Get(
        FallibleProcessResult,
        CCProcess(
            args=tuple(argv),
            language=field_set.language.normalized_value(),
            input_digest=input_digest,
            output_files=(compiled_object_name,),
            description=f"Compile CC source file: {target_file}",
            level=LogLevel.DEBUG,
        ),
    )

    logger.debug(compile_result.stderr)
    return FallibleCompiledCCObject(compiled_object_name, compile_result)


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
