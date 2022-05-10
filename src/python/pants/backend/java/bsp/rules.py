# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from dataclasses import dataclass

from pants.backend.java.bsp.spec import JavacOptionsItem, JavacOptionsParams, JavacOptionsResult
from pants.backend.java.target_types import JavaFieldSet, JavaSourceField
from pants.base.build_root import BuildRoot
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import BuildTargetIdentifier
from pants.bsp.util_rules.lifecycle import BSPLanguageSupport
from pants.bsp.util_rules.targets import (
    BSPBuildTargetsMetadataRequest,
    BSPBuildTargetsMetadataResult,
    BSPCompileRequest,
    BSPCompileResult,
    BSPResolveFieldFactoryRequest,
    BSPResolveFieldFactoryResult,
    BSPResourcesRequest,
    BSPResourcesResult,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.jvm.bsp.compile import _jvm_bsp_compile, jvm_classes_directory
from pants.jvm.bsp.compile import rules as jvm_compile_rules
from pants.jvm.bsp.resources import _jvm_bsp_resources
from pants.jvm.bsp.resources import rules as jvm_resources_rules
from pants.jvm.compile import ClasspathEntryRequestFactory
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField

LANGUAGE_ID = "java"

_logger = logging.getLogger(__name__)


class JavaBSPLanguageSupport(BSPLanguageSupport):
    language_id = LANGUAGE_ID
    can_compile = True
    can_provide_resources = True


@dataclass(frozen=True)
class JavaMetadataFieldSet(FieldSet):
    required_fields = (JavaSourceField, JvmResolveField)

    source: JavaSourceField
    resolve: JvmResolveField


class JavaBSPResolveFieldFactoryRequest(BSPResolveFieldFactoryRequest):
    resolve_prefix = "jvm"


class JavaBSPBuildTargetsMetadataRequest(BSPBuildTargetsMetadataRequest):
    language_id = LANGUAGE_ID
    can_merge_metadata_from = ()
    field_set_type = JavaMetadataFieldSet
    resolve_prefix = "jvm"
    resolve_field = JvmResolveField


@rule
def bsp_resolve_field_factory(
    request: JavaBSPResolveFieldFactoryRequest,
    jvm: JvmSubsystem,
) -> BSPResolveFieldFactoryResult:
    return BSPResolveFieldFactoryResult(
        lambda target: target.get(JvmResolveField).normalized_value(jvm)
    )


@rule
async def bsp_resolve_java_metadata(
    _: JavaBSPBuildTargetsMetadataRequest,
) -> BSPBuildTargetsMetadataResult:
    return BSPBuildTargetsMetadataResult()


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
    return HandleJavacOptionsResult(
        JavacOptionsItem(
            target=request.bsp_target_id,
            options=(),
            classpath=(),
            class_directory=build_root.pathlib_path.joinpath(
                f".pants.d/bsp/{jvm_classes_directory(request.bsp_target_id)}"
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
    result: BSPCompileResult = await _jvm_bsp_compile(request, classpath_entry_request)
    return result


# -----------------------------------------------------------------------------------------------
# Resources Request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class JavaBSPResourcesRequest(BSPResourcesRequest):
    field_set_type = JavaFieldSet


@rule
async def bsp_java_resources_request(
    request: JavaBSPResourcesRequest,
    build_root: BuildRoot,
) -> BSPResourcesResult:
    result: BSPResourcesResult = await _jvm_bsp_resources(request, build_root)
    return result


def rules():
    return (
        *collect_rules(),
        *jvm_compile_rules(),
        *jvm_resources_rules(),
        UnionRule(BSPLanguageSupport, JavaBSPLanguageSupport),
        UnionRule(BSPResolveFieldFactoryRequest, JavaBSPResolveFieldFactoryRequest),
        UnionRule(BSPBuildTargetsMetadataRequest, JavaBSPBuildTargetsMetadataRequest),
        UnionRule(BSPHandlerMapping, JavacOptionsHandlerMapping),
        UnionRule(BSPCompileRequest, JavaBSPCompileRequest),
        UnionRule(BSPResourcesRequest, JavaBSPResourcesRequest),
    )
