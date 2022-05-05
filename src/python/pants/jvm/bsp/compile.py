# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
import os

from pants.bsp.spec.base import BuildTargetIdentifier, StatusCode
from pants.bsp.util_rules.targets import BSPCompileRequest, BSPCompileResult
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, DigestEntries
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import rule_helper
from pants.engine.target import CoarsenedTargets
from pants.jvm.compile import (
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

    status = StatusCode.OK
    if any(r.exit_code != 0 for r in results):
        status = StatusCode.ERROR

    output_digest = EMPTY_DIGEST
    if status == StatusCode.OK:
        output_entries = []
        for result in results:
            if not result.output:
                continue
            entries = await Get(DigestEntries, Digest, result.output.digest)
            output_entries.extend(
                [
                    dataclasses.replace(
                        entry,
                        path=f"{jvm_classes_directory(request.bsp_target.bsp_target_id)}/{os.path.basename(entry.path)}",
                    )
                    for entry in entries
                ]
            )
        output_digest = await Get(Digest, CreateDigest(output_entries))

    return BSPCompileResult(
        status=status,
        output_digest=output_digest,
    )
