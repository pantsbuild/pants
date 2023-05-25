# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.core.target_types import (
    FilesGeneratingSourcesField,
    FileSourceField,
    RelocatedFilesSourcesField,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntry,
)


@dataclass(frozen=True)
class FileFieldSet(FieldSet):
    required_fields = (FileSourceField,)
    sources: FileSourceField


@dataclass(frozen=True)
class FilesGeneratorFieldSet(FieldSet):
    required_fields = (FilesGeneratingSourcesField,)
    sources: FilesGeneratingSourcesField


@dataclass(frozen=True)
class RelocatedFilesFieldSet(FieldSet):
    required_fields = (RelocatedFilesSourcesField,)
    sources: RelocatedFilesSourcesField


class NoopClasspathEntryRequest(ClasspathEntryRequest):
    field_sets = (FileFieldSet, FilesGeneratorFieldSet, RelocatedFilesFieldSet)


@rule(desc="Compile with javac")
async def noop_classpath_entry(
    request: NoopClasspathEntryRequest,
) -> FallibleClasspathEntry:
    return FallibleClasspathEntry(
        f"Empty classpath for no-op classpath target {request.component}",
        CompileResult.SUCCEEDED,
        ClasspathEntry(EMPTY_DIGEST, [], []),
        exit_code=0,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(ClasspathEntryRequest, NoopClasspathEntryRequest),
    ]
