# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
import logging
import os
from dataclasses import dataclass

from pants.backend.java.bsp.spec import JavacOptionsItem, JavacOptionsParams, JavacOptionsResult
from pants.backend.java.compile.javac import compute_output_jar_filename
from pants.backend.java.dependency_inference.symbol_mapper import AllJavaTargets
from pants.backend.java.target_types import JavaSourceField
from pants.base.build_root import BuildRoot
from pants.bsp.context import BSPContext
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import (
    BuildTarget,
    BuildTargetCapabilities,
    BuildTargetIdentifier,
    StatusCode,
)
from pants.bsp.util_rules.compile import BSPCompileFieldSet, BSPCompileResult
from pants.bsp.util_rules.lifecycle import BSPLanguageSupport
from pants.bsp.util_rules.targets import BSPBuildTargets, BSPBuildTargetsRequest
from pants.build_graph.address import Address, AddressInput
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, DigestEntries
from pants.engine.internals.native_engine import EMPTY_DIGEST, AddPrefix, Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    CoarsenedTargets,
    Dependencies,
    DependenciesRequest,
    Target,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.jvm.bsp.spec import JvmBuildTarget
from pants.jvm.compile import (
    ClasspathEntryRequest,
    ClasspathEntryRequestFactory,
    FallibleClasspathEntry,
)
from pants.jvm.resolve.key import CoursierResolveKey

LANGUAGE_ID = "java"

_logger = logging.getLogger(__name__)


class JavaBSPLanguageSupport(BSPLanguageSupport):
    language_id = LANGUAGE_ID
    can_compile = True


class JavaBSPBuildTargetsRequest(BSPBuildTargetsRequest):
    pass


@dataclass(frozen=True)
class ResolveJavaBSPBuildTargetRequest:
    target: Target


@rule
async def bsp_resolve_one_java_build_target(
    request: ResolveJavaBSPBuildTargetRequest,
    union_membership: UnionMembership,
) -> BuildTarget:
    dep_addrs = await Get(Addresses, DependenciesRequest(request.target[Dependencies]))
    impls = union_membership.get(BSPCompileFieldSet)

    reported_deps = []
    for dep_addr in dep_addrs:
        if dep_addr == request.target.address:
            continue

        wrapped_dep_tgt = await Get(WrappedTarget, Address, dep_addr)
        dep_tgt = wrapped_dep_tgt.target
        for impl in impls:
            if impl.is_applicable(dep_tgt):
                reported_deps.append(BuildTargetIdentifier.from_address(dep_tgt.address))
                break

    return BuildTarget(
        id=BuildTargetIdentifier.from_address(request.target.address),
        display_name=str(request.target.address),
        base_directory=None,
        tags=(),
        capabilities=BuildTargetCapabilities(
            can_compile=True,
        ),
        language_ids=(LANGUAGE_ID,),
        dependencies=tuple(reported_deps),
        data_kind="jvm",
        data=JvmBuildTarget(),
    )


@rule
async def bsp_resolve_all_java_build_targets(
    _: JavaBSPBuildTargetsRequest,
    all_java_targets: AllJavaTargets,
    bsp_context: BSPContext,
) -> BSPBuildTargets:
    if LANGUAGE_ID not in bsp_context.client_params.capabilities.language_ids:
        return BSPBuildTargets()
    build_targets = await MultiGet(
        Get(BuildTarget, ResolveJavaBSPBuildTargetRequest(tgt)) for tgt in all_java_targets
    )
    return BSPBuildTargets(targets=tuple(build_targets))


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
    wrapped_target = await Get(WrappedTarget, AddressInput, request.bsp_target_id.address_input)
    coarsened_targets = await Get(CoarsenedTargets, Addresses([wrapped_target.target.address]))
    assert len(coarsened_targets) == 1
    coarsened_target = coarsened_targets[0]
    resolve = await Get(CoursierResolveKey, CoarsenedTargets([coarsened_target]))
    output_file = compute_output_jar_filename(coarsened_target)

    return HandleJavacOptionsResult(
        JavacOptionsItem(
            target=request.bsp_target_id,
            options=(),
            classpath=(
                build_root.pathlib_path.joinpath(
                    f".pants.d/bsp/jvm/resolves/{resolve.name}/lib/{output_file}"
                ).as_uri(),
            ),
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
        UnionRule(BSPBuildTargetsRequest, JavaBSPBuildTargetsRequest),
        UnionRule(BSPHandlerMapping, JavacOptionsHandlerMapping),
        UnionRule(BSPCompileFieldSet, JavaBSPCompileFieldSet),
    )
