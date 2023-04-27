# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import time
from dataclasses import dataclass

from pants.bsp.context import BSPContext
from pants.bsp.spec.base import BuildTargetIdentifier, StatusCode, TaskId
from pants.bsp.spec.log import LogMessageParams, MessageType
from pants.bsp.spec.task import TaskProgressParams
from pants.bsp.util_rules.targets import BSPCompileRequest, BSPCompileResult
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import CoarsenedTargets
from pants.jvm import classpath
from pants.jvm.classpath import LooseClassfiles
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    ClasspathEntryRequestFactory,
    CompileResult,
    FallibleClasspathEntry,
)
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.target_types import JvmArtifactFieldSet
from pants.util.strutil import path_safe


def jvm_classes_directory(target_id: BuildTargetIdentifier) -> str:
    return f"jvm/classes/{path_safe(target_id.uri)}"


@dataclass(frozen=True)
class BSPClasspathEntryRequest:
    """A wrapper around a `ClasspathEntryRequest` which notifies the BSP client on completion.

    TODO: Because this struct contains a `task_id`, messages will re-render in every run, even
    though the underlying computation does not re-run. See #15426 for an alternative.
    """

    request: ClasspathEntryRequest
    task_id: TaskId


@rule
async def notify_for_classpath_entry(
    request: BSPClasspathEntryRequest,
    context: BSPContext,
) -> FallibleClasspathEntry:
    entry = await Get(FallibleClasspathEntry, ClasspathEntryRequest, request.request)
    context.notify_client(
        TaskProgressParams(
            task_id=request.task_id,
            event_time=int(time.time() * 1000),
            message=entry.message(),
        )
    )
    if entry.result == CompileResult.FAILED:
        context.notify_client(
            LogMessageParams(
                type_=MessageType.ERROR,
                message=entry.message(),
                task=request.task_id,
            )
        )
    return entry


async def _jvm_bsp_compile(
    request: BSPCompileRequest, classpath_entry_request: ClasspathEntryRequestFactory
) -> BSPCompileResult:
    """Generically handles a BSPCompileRequest (subclass).

    This is a rule helper rather than a `@rule`, because BSP backends like `java` and `scala`
    independently declare their `BSPCompileRequest` union members. We can't register a single shared
    `BSPCompileRequest` @union member for all JVM because their FieldSets are also declared via
    @unions, and we can't forward the implementation of a @union to another the way we might with
    an abstract class.
    """
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses([fs.address for fs in request.field_sets])
    )
    resolve = await Get(CoursierResolveKey, CoarsenedTargets, coarsened_targets)

    # TODO: We include the (non-3rdparty) transitive dependencies here, because each project
    # currently only has a single BuildTarget. This has the effect of including `resources` targets,
    # which are referenced by BuildTargets (via `buildTarget/resources`), rather than necessarily
    # being owned by any particular BuildTarget.
    #
    # To resolve #15051, this will no longer be transitive, and so `resources` will need to be
    # attached-to/referenced-by nearby BuildTarget(s) instead (most likely: direct dependent(s)).
    results = await MultiGet(
        Get(
            FallibleClasspathEntry,
            BSPClasspathEntryRequest(
                classpath_entry_request.for_targets(component=coarsened_target, resolve=resolve),
                task_id=request.task_id,
            ),
        )
        for coarsened_target in coarsened_targets.coarsened_closure()
        if not any(JvmArtifactFieldSet.is_applicable(t) for t in coarsened_target.members)
    )

    entries = FallibleClasspathEntry.if_all_succeeded(results)
    if entries is None:
        return BSPCompileResult(
            status=StatusCode.ERROR,
            output_digest=EMPTY_DIGEST,
        )

    loose_classfiles = await MultiGet(
        Get(LooseClassfiles, ClasspathEntry, entry) for entry in entries
    )
    merged_loose_classfiles = await Get(Digest, MergeDigests(lc.digest for lc in loose_classfiles))
    output_digest = await Get(
        Digest,
        AddPrefix(merged_loose_classfiles, jvm_classes_directory(request.bsp_target.bsp_target_id)),
    )

    return BSPCompileResult(
        status=StatusCode.OK,
        output_digest=output_digest,
    )


def rules():
    return [
        *collect_rules(),
        *classpath.rules(),
    ]
