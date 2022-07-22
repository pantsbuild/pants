# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.cc.subsystems.toolchain import CCToolchain
from pants.backend.cc.target_types import CCSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.unions import UnionRule

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
    source: CCSourceField


@rule(desc="Compile CC source with the current toolchain")
async def compile_cc_source(
    toolchain: CCToolchain, request: CompileCCSourceRequest
) -> FallibleCompiledCCObject:
    source_files = await Get(
        SourceFiles,
        SourceFilesRequest([request.source]),
    )
    compile_result = await Get(
        FallibleProcessResult,
        Process(
            argv=(
                toolchain.c,
                "-c",
                *source_files.files,
            ),
            input_digest=source_files.snapshot.digest,
            description="Compile CC source file",
            output_files=(f"{request.source.value}.o",),
        ),
    )
    return FallibleCompiledCCObject(request.source.value, compile_result)


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
