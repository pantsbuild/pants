# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
import logging
import os
from dataclasses import dataclass

from pants.backend.java.bsp.spec import JavacOptionsItem, JavacOptionsParams, JavacOptionsResult
from pants.backend.java.target_types import JavaSourceField
from pants.base.build_root import BuildRoot
from pants.base.specs import AddressSpecs
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import BuildTargetIdentifier, StatusCode
from pants.bsp.util_rules.compile import BSPCompileFieldSet, BSPCompileResult
from pants.bsp.util_rules.lifecycle import BSPLanguageSupport
from pants.bsp.util_rules.targets import (
    BSPBuildTargetsMetadataRequest,
    BSPBuildTargetsMetadataResult,
    BSPBuildTargetsNew,
)
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, DigestEntries
from pants.engine.internals.native_engine import EMPTY_DIGEST, AddPrefix, Digest
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
    bsp_build_targets: BSPBuildTargetsNew,
) -> HandleJavacOptionsResult:
    bsp_target_name = request.bsp_target_id.uri[len("pants:") :]
    if bsp_target_name not in bsp_build_targets.targets_mapping:
        raise ValueError(f"Invalid BSP target name: {request.bsp_target_id}")
    targets = await Get(
        Targets,
        AddressSpecs,
        bsp_build_targets.targets_mapping[bsp_target_name].specs.address_specs,
    )

    coarsened_targets = await Get(CoarsenedTargets, Addresses(tgt.address for tgt in targets))
    # assert len(coarsened_targets) == 1
    # coarsened_target = coarsened_targets[0]
    resolve = await Get(CoursierResolveKey, CoarsenedTargets, coarsened_targets)
    # output_file = compute_output_jar_filename(coarsened_target)

    return HandleJavacOptionsResult(
        JavacOptionsItem(
            target=request.bsp_target_id,
            options=(),
            # classpath=(
            #     build_root.pathlib_path.joinpath(
            #         f".pants.d/bsp/jvm/resolves/{resolve.name}/lib/{output_file}"
            #     ).as_uri(),
            # ),
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
class JavaBSPCompileFieldSet(BSPCompileFieldSet):
    required_fields = (JavaSourceField,)
    source: JavaSourceField


@rule
async def bsp_java_compile_request(
    request: JavaBSPCompileFieldSet, classpath_entry_request: ClasspathEntryRequestFactory
) -> BSPCompileResult:
    coarsened_targets = await Get(CoarsenedTargets, Addresses([request.source.address]))
    assert len(coarsened_targets) == 1
    coarsened_target = coarsened_targets[0]
    resolve = await Get(CoursierResolveKey, CoarsenedTargets([coarsened_target]))

    result = await Get(
        FallibleClasspathEntry,
        ClasspathEntryRequest,
        classpath_entry_request.for_targets(component=coarsened_target, resolve=resolve),
    )
    _logger.info(f"java compile result = {result}")
    output_digest = EMPTY_DIGEST
    if result.exit_code == 0 and result.output:
        entries = await Get(DigestEntries, Digest, result.output.digest)
        new_entires = [
            dataclasses.replace(entry, path=os.path.basename(entry.path)) for entry in entries
        ]
        flat_digest = await Get(Digest, CreateDigest(new_entires))
        output_digest = await Get(
            Digest, AddPrefix(flat_digest, f"jvm/resolves/{resolve.name}/lib")
        )

    return BSPCompileResult(
        status=StatusCode.ERROR if result.exit_code != 0 else StatusCode.OK,
        output_digest=output_digest,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(BSPLanguageSupport, JavaBSPLanguageSupport),
        UnionRule(BSPBuildTargetsMetadataRequest, JavaBSPBuildTargetsMetadataRequest),
        UnionRule(BSPHandlerMapping, JavacOptionsHandlerMapping),
        UnionRule(BSPCompileFieldSet, JavaBSPCompileFieldSet),
    )
