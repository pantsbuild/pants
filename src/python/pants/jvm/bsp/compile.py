# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import time
from collections.abc import Iterable
from dataclasses import dataclass

from pants.bsp.context import BSPContext
from pants.bsp.spec.base import BuildTargetIdentifier, StatusCode, TaskId
from pants.bsp.spec.log import LogMessageParams, MessageType
from pants.bsp.spec.task import TaskProgressParams
from pants.bsp.util_rules.targets import BSPCompileRequest, BSPCompileResult
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, CreateDigest, FileEntry
from pants.engine.internals.graph import resolve_coarsened_targets
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import add_prefix, create_digest, get_digest_entries
from pants.engine.rules import collect_rules, implicitly, rule
from pants.jvm import classpath
from pants.jvm.compile import (
    ClasspathEntryRequest,
    ClasspathEntryRequestFactory,
    CompileResult,
    FallibleClasspathEntry,
    get_fallible_classpath_entry,
)
from pants.jvm.resolve.coursier_fetch import select_coursier_resolve_for_targets
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
    entry = await get_fallible_classpath_entry(
        **implicitly({request.request: ClasspathEntryRequest})
    )
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


def _first_occurrence_file_entries(
    per_classpath_entries: Iterable[Iterable[object]],
) -> list[FileEntry]:
    """Walk per-classpath-entry digest contents (each a
    sequence of ``FileEntry`` / ``SymlinkEntry`` / ``Directory``) and return a
    flat list of ``FileEntry`` values keeping the first occurrence per path.
    Non-``FileEntry`` items are dropped — they're either implicit directory
    parents (re-created by ``CreateDigest``) or symlinks not produced by the
    JVM compile path.
    """
    seen_paths: set[str] = set()
    kept: list[FileEntry] = []
    for entries in per_classpath_entries:
        for entry in entries:
            if not isinstance(entry, FileEntry):
                continue
            if entry.path in seen_paths:
                continue
            seen_paths.add(entry.path)
            kept.append(entry)
    return kept


async def _dedupe_loose_classfiles(
    loose_classfiles: tuple[classpath.LooseClassfiles, ...],
) -> Digest:
    """Merge the loose-classfile digests from a BSP compile closure, keeping the
    first-occurrence entry per file path on path collisions.

    Multiple compile-closure members can contribute the same path to the merged
    BSP output (e.g. two different first-party modules each shipping a
    `logback.xml` resource in their classpath jar, both ending up in the same
    BSP target's class directory). The plain ``merge_digests(MergeDigests(...))``
    call raises ``IntrinsicError: Can only merge Directories with no duplicates``
    in that case. JVM classpath semantics tolerate duplicate paths by picking
    the first occurrence; we mirror that here so BSP compile of a multi-module
    target succeeds rather than failing on collisions.
    """
    per_entry = await concurrently(get_digest_entries(lc.digest) for lc in loose_classfiles)
    kept = _first_occurrence_file_entries([list(entries) for entries in per_entry])
    return await create_digest(CreateDigest(kept))


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
    coarsened_targets = await resolve_coarsened_targets(
        **implicitly(Addresses([fs.address for fs in request.field_sets]))
    )
    resolve = await select_coursier_resolve_for_targets(coarsened_targets, **implicitly())

    # TODO: We include the (non-3rdparty) transitive dependencies here, because each project
    # currently only has a single BuildTarget. This has the effect of including `resources` targets,
    # which are referenced by BuildTargets (via `buildTarget/resources`), rather than necessarily
    # being owned by any particular BuildTarget.
    #
    # To resolve #15051, this will no longer be transitive, and so `resources` will need to be
    # attached-to/referenced-by nearby BuildTarget(s) instead (most likely: direct dependent(s)).
    results = await concurrently(
        notify_for_classpath_entry(
            BSPClasspathEntryRequest(
                classpath_entry_request.for_targets(component=coarsened_target, resolve=resolve),
                task_id=request.task_id,
            ),
            **implicitly(),
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

    loose_clsfiles = await concurrently(
        classpath.loose_classfiles(entry, **implicitly()) for entry in entries
    )
    merged_loose_classfiles = await _dedupe_loose_classfiles(tuple(loose_clsfiles))
    output_digest = await add_prefix(
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
