# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
import logging
import os
from dataclasses import dataclass

from pants.backend.java.bsp.spec import JavacOptionsItem, JavacOptionsParams, JavacOptionsResult
from pants.backend.java.target_types import JavaFieldSet, JavaSourceField
from pants.base.build_root import BuildRoot
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import BuildTargetIdentifier, StatusCode
from pants.bsp.util_rules.compile import BSPCompileRequest, BSPCompileResult
from pants.bsp.util_rules.lifecycle import BSPLanguageSupport
from pants.bsp.util_rules.targets import (
    BSPBuildTargetsMetadataRequest,
    BSPBuildTargetsMetadataResult,
)
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, DigestEntries
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import CoarsenedTargets, FieldSet, Targets
from pants.engine.unions import UnionRule
from pants.jvm.compile import (
    ClasspathEntryRequest,
    ClasspathEntryRequestFactory,
    FallibleClasspathEntry,
)
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.target_types import JvmResolveField

LANGUAGE_ID = "java"

_logger = logging.getLogger(__name__)


class JavaBSPLanguageSupport(BSPLanguageSupport):
    language_id = LANGUAGE_ID
    can_compile = True


@dataclass(frozen=True)
class JavaMetadataFieldSet(FieldSet):
    required_fields = (JavaSourceField, JvmResolveField)

    source: JavaSourceField
    resolve: JvmResolveField


class JavaBSPBuildTargetsMetadataRequest(BSPBuildTargetsMetadataRequest):
    language_id = LANGUAGE_ID
    can_merge_metadata_from = ()
    field_set_type = JavaMetadataFieldSet


@rule
async def bsp_resolve_java_metadata(
    _: JavaBSPBuildTargetsMetadataRequest,
) -> BSPBuildTargetsMetadataResult:
    return BSPBuildTargetsMetadataResult(
        can_compile=True,
    )


# -----------------------------------------------------------------------------------------------
# Javac Options Request
# See https://build-server-protocol.github.io/docs/extensions/java.html#javac-options-request
# -----------------------------------------------------------------------------------------------


class JavacOptionsHandlerMapping(BSPHandlerMapping):
    method_name = "buildTarget/javacOptions"
    request_type = JavacOptionsParams
    response_type = JavacOptionsResult


@dataclass(frozen=True)
class HandleJavacOptionsRequest:
    bsp_target_id: BuildTargetIdentifier


@dataclass(frozen=True)
class HandleJavacOptionsResult:
    item: JavacOptionsItem


@rule
async def handle_bsp_java_options_request(
    request: HandleJavacOptionsRequest,
    build_root: BuildRoot,
) -> HandleJavacOptionsResult:
    targets = await Get(Targets, BuildTargetIdentifier, request.bsp_target_id)

    coarsened_targets = await Get(CoarsenedTargets, Addresses(tgt.address for tgt in targets))
    resolve = await Get(CoursierResolveKey, CoarsenedTargets, coarsened_targets)

    return HandleJavacOptionsResult(
        JavacOptionsItem(
            target=request.bsp_target_id,
            options=(),
            classpath=(),
            class_directory=build_root.pathlib_path.joinpath(
                f".pants.d/bsp/jvm/resolves/{resolve.name}/classes"
            ).as_uri(),
        )
    )


@rule
async def bsp_javac_options_request(request: JavacOptionsParams) -> JavacOptionsResult:
    results = await MultiGet(
        Get(HandleJavacOptionsResult, HandleJavacOptionsRequest(btgt)) for btgt in request.targets
    )
    return JavacOptionsResult(items=tuple(result.item for result in results))


# -----------------------------------------------------------------------------------------------
# Compile Request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class JavaBSPCompileRequest(BSPCompileRequest):
    field_set_type = JavaFieldSet


@rule
async def bsp_java_compile_request(
    request: JavaBSPCompileRequest, classpath_entry_request: ClasspathEntryRequestFactory
) -> BSPCompileResult:
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
                        path=f"jvm/resolves/{resolve.name}/lib/{os.path.basename(entry.path)}",
                    )
                    for entry in entries
                ]
            )
        output_digest = await Get(Digest, CreateDigest(output_entries))

    return BSPCompileResult(
        status=status,
        output_digest=output_digest,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(BSPLanguageSupport, JavaBSPLanguageSupport),
        UnionRule(BSPBuildTargetsMetadataRequest, JavaBSPBuildTargetsMetadataRequest),
        UnionRule(BSPHandlerMapping, JavacOptionsHandlerMapping),
        UnionRule(BSPCompileRequest, JavaBSPCompileRequest),
    )
