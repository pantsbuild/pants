# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.scala.target_types import ScalaArtifactFieldSet
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.compile import (
    ClasspathDependenciesRequest,
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntries,
    FallibleClasspathEntry,
)


class ScalaArtifactClasspathEntryRequest(ClasspathEntryRequest):
    field_sets = (ScalaArtifactFieldSet,)


@rule
async def scala_artifact_classpath(
    request: ScalaArtifactClasspathEntryRequest,
) -> FallibleClasspathEntry:
    fallible_entries = await Get(FallibleClasspathEntries, ClasspathDependenciesRequest(request))
    classpath_entries = fallible_entries.if_all_succeeded()
    if classpath_entries is None:
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )
    return FallibleClasspathEntry(
        description=str(request.component),
        result=CompileResult.SUCCEEDED,
        output=ClasspathEntry(EMPTY_DIGEST, dependencies=classpath_entries),
        exit_code=0,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(ClasspathEntryRequest, ScalaArtifactClasspathEntryRequest),
    ]
