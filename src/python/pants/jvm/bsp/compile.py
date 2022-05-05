# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.bsp.spec.base import BuildTargetIdentifier, StatusCode
from pants.bsp.util_rules.targets import BSPCompileRequest, BSPCompileResult
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule_helper
from pants.engine.target import CoarsenedTargets
from pants.jvm import classpath
from pants.jvm.classpath import LooseClassfiles
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    ClasspathEntryRequestFactory,
    FallibleClasspathEntry,
)
from pants.jvm.resolve.key import CoursierResolveKey
from pants.util.strutil import path_safe


def jvm_classes_directory(target_id: BuildTargetIdentifier) -> str:
    return f"jvm/classes/{path_safe(target_id.uri)}"


@rule_helper
async def _jvm_bsp_compile(
    request: BSPCompileRequest, classpath_entry_request: ClasspathEntryRequestFactory
) -> BSPCompileResult:
    """Generically handles a BSPCompileRequest (subclass).

    This is a `@rule_helper` rather than a `@rule`, because BSP backends like `java` and `scala`
    independently declare their `BSPCompileRequest` union members. We can't register a single shared
    `BSPCompileRequest` @union member for all JVM because their FieldSets are also declared via
    @unions, and we can't forward the implementation of a @union to another the way we might with
    an abstract class.
    """
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses([fs.address for fs in request.field_sets])
    )
    resolve = await Get(CoursierResolveKey, CoarsenedTargets, coarsened_targets)

    results = await MultiGet(
        Get(
            FallibleClasspathEntry,
            ClasspathEntryRequest,
            classpath_entry_request.for_targets(component=coarsened_target, resolve=resolve),
        )
        for coarsened_target in coarsened_targets
    )

    entries = FallibleClasspathEntry.if_all_succeeded(results)
    if entries is None:
        return BSPCompileResult(
            status=StatusCode.ERROR,
            output_digest=EMPTY_DIGEST,
        )

    # NB: We are not including the transitive dependencies here: only the targets actually matched
    # by the roots. All others are exposed as transitive module dependencies.
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
