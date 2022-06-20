# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.swift.subsystems.toolchain import SwiftToolchain
from pants.backend.swift.target_types import SwiftFieldSet, SwiftSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.target import SourcesField, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class CompileSwiftSourceRequest:
    field_sets = (SwiftFieldSet,)


@dataclass(frozen=True)
class TypecheckSwiftModuleRequest:
    name: str
    targets: Iterable[Target]


@dataclass(frozen=True)
class FallibleTypecheckedSwiftModule:
    name: str
    process_result: FallibleProcessResult


@rule(desc="Typechecking a single swift module", level=LogLevel.DEBUG)
async def typecheck_swift_module(
    toolchain: SwiftToolchain, request: TypecheckSwiftModuleRequest
) -> FallibleTypecheckedSwiftModule:

    # Get the source files for the passed in targets
    source_fields = [target.get(SourcesField) for target in request.targets]
    source_files = await Get(
        SourceFiles,
        SourceFilesRequest(source_fields, for_sources_types=(SwiftSourceField,)),
    )

    # Run with the `-typecheck` flag, which avoids several compilation steps (very fast)
    result = await Get(
        FallibleProcessResult,
        Process(
            argv=(
                toolchain.exe,
                "-typecheck",
                *source_files.files,
            ),
            input_digest=source_files.snapshot.digest,
            description=f"Typechecking swift module with {pluralize(len(source_files.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )

    return FallibleTypecheckedSwiftModule(request.name, result)


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
