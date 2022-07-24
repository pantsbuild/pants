# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.cc.dependency_inference.rules import (
    CCDependencyInferenceFieldSet,
    InferCCDependenciesRequest,
)
from pants.backend.cc.subsystems.toolchain import CCToolchain
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, rule
from pants.engine.target import (
    InferredDependencies,
    SourcesField,
    Target,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)

# @dataclass(frozen=True)
# class CompileCCSourceRequest:
#     name: str
#     targets: Iterable[Target]


@dataclass(frozen=True)
class FallibleCompiledCCObject:
    name: str
    process_result: FallibleProcessResult


@dataclass(frozen=True)
class CompileCCSourceRequest:
    # field_sets = (CCFieldSet, CCGeneratorFieldSet)
    target: Target


@rule(desc="Compile CC source with the current toolchain")
async def compile_cc_source(
    toolchain: CCToolchain, request: CompileCCSourceRequest
) -> FallibleCompiledCCObject:

    target_source_file = await Get(
        SourceFiles, SourceFilesRequest([request.target.get(SourcesField)])
    )

    deps = await Get(
        InferredDependencies,
        InferCCDependenciesRequest(CCDependencyInferenceFieldSet.create(request.target)),
    )

    wrapped_targets = await MultiGet(
        Get(
            WrappedTarget,
            WrappedTargetRequest(dep, description_of_origin="<build_pkg_target.py>"),
        )
        for dep in deps.include
    )

    source_files = await Get(
        SourceFiles, SourceFilesRequest([dep.target.get(SourcesField) for dep in wrapped_targets])
    )
    logger.warning(f"SourceFIles:  {source_files}")

    input_digest = await Get(
        Digest,
        MergeDigests((target_source_file.snapshot.digest, source_files.snapshot.digest)),
    )

    argv = (toolchain.c, "-c", *target_source_file.files, *source_files.files)
    logger.error(f"argv:  {argv}")

    compiled_object_name = f"{request.target.address}.o"
    compile_result = await Get(
        FallibleProcessResult,
        Process(
            argv=argv,
            input_digest=input_digest,
            description=f"Compile CC source file: {request.target.address}",
            output_files=(compiled_object_name,),
        ),
    )
    # logger.error(request.source.value)
    return FallibleCompiledCCObject(compiled_object_name, compile_result)


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
